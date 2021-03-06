from flask import request, redirect, url_for, render_template, abort, flash
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired

from uchan import configuration
from uchan.lib import ArgumentError
from uchan.lib import roles
from uchan.lib.cache import board_cache
from uchan.lib.mod_log import mod_log
from uchan.lib.models.moderator_log import ModeratorLogType
from uchan.lib.moderator_request import request_moderator
from uchan.lib.service import board_service, moderator_service, config_service
from uchan.mod import mod
from uchan.view import check_csrf_token, with_token
from uchan.view.form import CSRFForm
from uchan.view.form.validators import BoardValidator


def get_board_or_abort(board_name):
    if not board_name or not board_service.check_board_name_validity(board_name):
        abort(400)

    board = board_service.find_board(board_name)
    if not board:
        abort(404)
    return board


class AddBoardForm(CSRFForm):
    name = 'Create new board'
    action = '.mod_boards'

    board_name = StringField('Board name', [DataRequired(), BoardValidator()],
                             description='Name of the board. This name is used in the url and cannot be changed, '
                                         'so choose carefully. You can have a maximum of (' +
                                         str(configuration.app.max_boards_per_moderator) + ') boards.')
    submit = SubmitField('Create board')


@mod.route('/mod_board', methods=['GET', 'POST'])
def mod_boards():
    moderator = request_moderator()

    add_board_form = AddBoardForm(request.form)
    if request.method == 'POST' and add_board_form.validate():
        try:
            board_name = add_board_form.board_name.data
            moderator_service.user_create_board(moderator, board_name)
            flash('Board created')
            return redirect(url_for('.mod_board', board_name=board_name))
        except ArgumentError as e:
            flash(e.message)
            return redirect(url_for('.mod_boards'))

    return render_template('mod_boards.html', add_board_form=add_board_form, moderator=moderator)


@mod.route('/mod_board/<board_name>', methods=['GET', 'POST'])
def mod_board(board_name):
    board = get_board_or_abort(board_name)

    moderator = request_moderator()
    if not moderator_service.moderates_board(moderator, board):
        abort(404)

    board_config_row = board.config
    if request.method == 'GET':
        board_config = config_service.load_config(board_config_row, moderator)

        # Put the request moderator on top
        board_moderators_unsorted = sorted(board.board_moderators,
                                           key=lambda board_moderator: board_moderator.moderator.id)
        board_moderators = []
        for item in board_moderators_unsorted:
            if item.moderator == moderator:
                board_moderators.append(item)
                break
        for item in board_moderators_unsorted:
            if item.moderator != moderator:
                board_moderators.append(item)

        all_board_roles = roles.ALL_BOARD_ROLES

        can_delete = moderator_service.has_role(moderator, roles.ROLE_ADMIN)
        return render_template('mod_board.html', board=board, board_config=board_config,
                               board_moderators=board_moderators, can_delete=can_delete,
                               all_board_roles=all_board_roles)
    else:
        # Don't filter on permission when loading the config here.
        # If you would filter the configs here then configs set by mods that do have the permission get lost.
        # Permission checking is done when saving.
        board_config = config_service.load_config(board_config_row, None)

        form = request.form

        if not check_csrf_token(form.get('token')):
            abort(400)

        try:
            moderator_service.user_update_board_config(moderator, board, board_config, board_config_row, form)
            flash('Board config updated')
            mod_log('board /{}/ config updated'.format(board_name))
            board_cache.invalidate_board_config(board_name)
        except ArgumentError as e:
            flash(str(e))

        return redirect(url_for('.mod_board', board_name=board_name))


@mod.route('/mod_board/<board_name>/log')
@mod.route('/mod_board/<board_name>/log/<int(max=14):page>')
def mod_board_log(board_name, page=0):
    per_page = 100
    pages = 15

    board = get_board_or_abort(board_name)

    moderator = request_moderator()

    logs = moderator_service.user_get_logs(moderator, board, page, per_page)

    def get_log_type(typeid):
        try:
            return ModeratorLogType(typeid).name
        except ValueError:
            return ''

    return render_template('mod_board_log.html', board=board, page=page, pages=pages,
                           logs=logs, get_log_type=get_log_type)


@mod.route('/mod_board/<board_name>/moderator_invite', methods=['POST'])
@with_token()
def mod_board_moderator_invite(board_name):
    board = get_board_or_abort(board_name)

    form = request.form

    moderator_username = form['username']

    try:
        moderator_service.user_invite_moderator(request_moderator(), board, moderator_username)
        flash('Moderator invited')
    except ArgumentError as e:
        flash(str(e))

    return redirect(url_for('.mod_board', board_name=board.name))


@mod.route('/mod_board/<board_name>/moderator_remove', methods=['POST'])
@with_token()
def mod_board_moderator_remove(board_name):
    board = get_board_or_abort(board_name)
    form = request.form
    moderator_username = form['username']

    removed_self = False
    try:
        removed_self = moderator_service.user_remove_moderator(request_moderator(), board, moderator_username)
        flash('Moderator removed')
    except ArgumentError as e:
        flash(str(e))

    if removed_self:
        return redirect(url_for('.mod_boards'))
    else:
        return redirect(url_for('.mod_board', board_name=board.name))


@mod.route('/mod_board/<board_name>/roles_update', methods=['POST'])
@with_token()
def mod_board_roles_update(board_name):
    board = get_board_or_abort(board_name)
    form = request.form
    moderator_username = form['username']

    checked_roles = []
    for board_role in roles.ALL_BOARD_ROLES:
        if form.get(board_role) == 'on':
            checked_roles.append(board_role)

    try:
        moderator_service.user_update_roles(request_moderator(), board, moderator_username, checked_roles)
        flash('Roles updated')
    except ArgumentError as e:
        flash(str(e))

    return redirect(url_for('.mod_board', board_name=board.name))


@mod.route('/mod_board/delete', methods=['POST'])
@with_token()
def mod_board_delete():
    board = get_board_or_abort(request.form['board_name'])

    try:
        moderator_service.user_delete_board(request_moderator(), board)
        flash('Board deleted')
        mod_log('delete board /{}/'.format(board.name))
    except ArgumentError as e:
        flash(e.message)

    return redirect(url_for('.mod_boards'))
