from flask import redirect
from flask import render_template, abort
from flask import url_for

from uchan import app
from uchan.lib.cache import board_cache, posts_cache, site_cache
from uchan.lib.moderator_request import get_authed, request_moderator
from uchan.lib.utils import valid_id_range
from uchan.lib.service import posts_service, moderator_service


def get_board_view_params(board_config, mode, board_name, additional_page_details=None):
    global_posting_enabled = site_cache.find_site_config().get('file_posting_enabled')
    file_posting_enabled = board_config.get('file_posting_enabled') and global_posting_enabled

    details = {
        'mode': mode,
        'boardName': board_name,
        'postEndpoint': url_for('post')
    }
    if file_posting_enabled:
        details['filePostingEnabled'] = file_posting_enabled
    if additional_page_details:
        details.update(additional_page_details)

    return {
        'full_name': board_config.get('full_name'),
        'description': board_config.get('description'),
        'pages': board_config.get('pages'),
        'file_posting_enabled': file_posting_enabled,
        'page_details': details
    }


def show_moderator_buttons(board_id):
    if get_authed():
        moderator = request_moderator()
        if moderator_service.moderates_board_id(moderator, board_id):
            return True

    return False


@app.route('/<string(maxlength=20):board_name>/')
@app.route('/<string(maxlength=20):board_name>/<int:page>')
def board(board_name, page=None):
    board_config = board_cache.find_board_config(board_name)
    if not board_config:
        abort(404)

    if page == 1:
        return redirect(url_for('board', board_name=board_name))

    if page is None:
        page = 1

    if page <= 0 or page > board_config.get('pages'):
        abort(404)

    page -= 1

    board_cached = posts_cache.find_board_cached(board_name, page)
    if not board_cached:
        abort(404)

    return render_template('board.html', board=board_cached.board, threads=board_cached.threads,
                           show_moderator_buttons=show_moderator_buttons(board_cached.board.id),
                           page_index=page,
                           **get_board_view_params(board_config, 'board', board_name))


@app.route('/<string(maxlength=20):board_name>/view/<int:thread_id>')
def view_thread_id(board_name, thread_id):
    valid_id_range(thread_id)

    thread = posts_service.find_thread(thread_id, False)
    if thread:
        return redirect(url_for('.view_thread', board_name=thread.board.name, thread_refno=thread.refno))
    abort(404)


@app.route('/<string(maxlength=20):board_name>/read/<int:thread_refno>')
def view_thread(board_name, thread_refno):
    valid_id_range(thread_refno)

    board_config = board_cache.find_board_config(board_name)
    if not board_config:
        abort(404)

    thread_cached = posts_cache.find_thread_cached(board_name, thread_refno)

    if not thread_cached or thread_cached.board.name != board_name:
        abort(404)

    additional_page_details = {
        'threadRefno': thread_cached.refno
    }
    if thread_cached.locked:
        additional_page_details['locked'] = True
    if thread_cached.sticky:
        additional_page_details['sticky'] = True

    return render_template('thread.html', thread=thread_cached, board=thread_cached.board,
                           show_moderator_buttons=show_moderator_buttons(thread_cached.board.id),
                           **get_board_view_params(board_config, 'thread', board_name, additional_page_details))


@app.route('/<string(maxlength=20):board_name>/catalog')
def board_catalog(board_name):
    board_config = board_cache.find_board_config(board_name)
    if not board_config:
        abort(404)

    board_cached = posts_cache.find_board_cached(board_name)
    if not board_cached:
        abort(404)

    return render_template('catalog.html', board=board_cached.board, threads=board_cached.threads,
                           **get_board_view_params(board_config, 'catalog', board_name))
