from flask import request, redirect, url_for, render_template, abort, flash

from uchan.lib import roles, ArgumentError
from uchan.lib.mod_log import mod_log
from uchan.lib.models import Moderator
from uchan.lib.moderator_request import request_moderator, unset_mod_authed
from uchan.lib.utils import valid_id_range
from uchan.mod import mod, mod_role_restrict
from uchan.view import with_token
from uchan.lib.service import board_service, moderator_service


def get_moderator_or_abort(moderator_id):
    valid_id_range(moderator_id)

    moderator = moderator_service.find_moderator_id(moderator_id)
    if not moderator:
        abort(404)
    return moderator


@mod.route('/mod_moderator')
@mod_role_restrict(roles.ROLE_ADMIN)
def mod_moderators():
    moderators = moderator_service.get_all_moderators()

    return render_template('mod_moderators.html', moderators=moderators)


@mod.route('/mod_moderator/add', methods=['POST'])
@mod_role_restrict(roles.ROLE_ADMIN)
@with_token()
def mod_moderator_add():
    moderator_name = request.form['moderator_name']
    if not moderator_service.check_username_validity(moderator_name):
        flash('Invalid moderator name')
        return redirect(url_for('.mod_moderators'))

    moderator_password = request.form['moderator_password']
    if not moderator_service.check_password_validity(moderator_password):
        flash('Invalid moderator password')
        return redirect(url_for('.mod_moderators'))

    moderator = Moderator()
    moderator.roles = []
    moderator.username = moderator_name

    try:
        moderator_service.create_moderator(moderator, moderator_password)
        flash('Moderator added')
        mod_log('moderator add {} username {}'.format(moderator.id, moderator.username))
    except ArgumentError as e:
        flash(e.message)

    return redirect(url_for('.mod_moderators'))


@mod.route('/mod_moderator/delete', methods=['POST'])
@mod_role_restrict(roles.ROLE_ADMIN)
@with_token()
def mod_moderator_delete():
    moderator = get_moderator_or_abort(request.form.get('moderator_id', type=int))
    username = moderator.username

    authed_moderator = request_moderator()
    self_delete = authed_moderator == moderator

    moderator_service.delete_moderator(moderator)
    if self_delete:
        unset_mod_authed()
    flash('Moderator deleted')
    mod_log('moderator delete username {}'.format(username), moderator_name=authed_moderator.username)

    if self_delete:
        return redirect(url_for('.mod_auth'))
    else:
        return redirect(url_for('.mod_moderators'))


@mod.route('/mod_moderator/<int:moderator_id>')
@mod_role_restrict(roles.ROLE_ADMIN)
def mod_moderator(moderator_id):
    moderator = get_moderator_or_abort(moderator_id)

    all_roles = ', '.join(roles.ALL_ROLES)
    all_board_roles = ', '.join(roles.ALL_BOARD_ROLES)

    return render_template('mod_moderator.html', moderator=moderator, all_roles=all_roles,
                           all_board_roles=all_board_roles)


@mod.route('/mod_moderator/<int:moderator_id>/board_add', methods=['POST'])
@mod_role_restrict(roles.ROLE_ADMIN)
@with_token()
def mod_moderator_board_add(moderator_id):
    moderator = get_moderator_or_abort(moderator_id)

    board_name = request.form['board_name']
    board_role = request.form['board_role']
    board = board_service.find_board(board_name)
    if board is None:
        flash('That board does not exist')
    else:
        if not moderator_service.board_role_exists(board_role):
            flash('That board role does not exist')
        else:
            try:
                board_service.board_add_moderator(board, moderator)
                moderator_service.add_board_role(moderator, board, board_role)
                flash('Board added to moderator')
                mod_log('add board to {} /{}/ with role {}'.format(moderator.username, board_name, board_role))
            except ArgumentError as e:
                flash(e.message)

    return redirect(url_for('.mod_moderator', moderator_id=moderator_id))


@mod.route('/mod_moderator/<int:moderator_id>/board_remove', methods=['POST'])
@mod_role_restrict(roles.ROLE_ADMIN)
@with_token()
def mod_moderator_board_remove(moderator_id):
    moderator = get_moderator_or_abort(moderator_id)

    board_name = request.form['board_name']
    board = board_service.find_board(board_name)
    if board is None:
        flash('That board does not exist')
    else:
        try:
            board_service.board_remove_moderator(board, moderator)
            flash('Board removed from moderator')
            mod_log('remove board from {} /{}/'.format(moderator.username, board_name))
        except ArgumentError as e:
            flash(e.message)

    return redirect(url_for('.mod_moderator', moderator_id=moderator_id))


@mod.route('/mod_moderator/<int:moderator_id>/change_password', methods=['POST'])
@mod_role_restrict(roles.ROLE_ADMIN)
@with_token()
def mod_moderator_password(moderator_id):
    moderator = get_moderator_or_abort(moderator_id)

    new_password = request.form['new_password']

    if not moderator_service.check_password_validity(new_password):
        flash('Invalid password')
        return redirect(url_for('.mod_moderator', moderator_id=moderator_id))

    try:
        moderator_service.change_password_admin(moderator, new_password)
        flash('Changed password')
        mod_log('changed password for {}'.format(moderator.username))
    except ArgumentError as e:
        flash(e.message)

    return redirect(url_for('.mod_moderator', moderator_id=moderator_id))


@mod.route('/mod_moderator/<int:moderator_id>/role_add', methods=['POST'])
@mod_role_restrict(roles.ROLE_ADMIN)
@with_token()
def mod_moderator_role_add(moderator_id):
    moderator = get_moderator_or_abort(moderator_id)

    role = request.form['role']

    if not moderator_service.role_exists(role):
        flash('That role does not exist')
    else:
        try:
            moderator_service.add_role(moderator, role)
            flash('Role added')
            mod_log('add role {} to {}'.format(role, moderator.username))
        except ArgumentError as e:
            flash(e.message)

    return redirect(url_for('.mod_moderator', moderator_id=moderator_id))


@mod.route('/mod_moderator/<int:moderator_id>/role_remove', methods=['POST'])
@mod_role_restrict(roles.ROLE_ADMIN)
@with_token()
def mod_moderator_role_remove(moderator_id):
    moderator = get_moderator_or_abort(moderator_id)

    role = request.form['role']

    if not moderator_service.role_exists(role):
        flash('That role does not exist')
    else:
        try:
            moderator_service.remove_role(moderator, role)
            flash('Role removed')
            mod_log('remove role {} from {}'.format(role, moderator.username))
        except ArgumentError as e:
            flash(e.message)

    return redirect(url_for('.mod_moderator', moderator_id=moderator_id))
