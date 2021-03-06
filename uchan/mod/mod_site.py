from flask import request, render_template, abort, flash, redirect, url_for, session

from uchan import app
from uchan.lib import roles, ArgumentError
from uchan.lib.configs import SiteConfig
from uchan.lib.database import get_db
from uchan.lib.mod_log import mod_log
from uchan.lib.models import Board, Post, Thread, Session, Ban, Report, Moderator, File, Config
from uchan.lib.moderator_request import request_moderator
from uchan.lib.proxy_request import get_request_ip4_str
from uchan.lib.service import config_service
from uchan.lib.cache import cache, site_cache
from uchan.mod import mod, mod_role_restrict
from uchan.view import check_csrf_token, with_token


@mod.route('/mod_site', methods=['GET', 'POST'])
@mod_role_restrict(roles.ROLE_ADMIN)
def mod_site():
    site_config_row = config_service.get_config_by_type(SiteConfig.TYPE)
    site_config = config_service.load_config(site_config_row)
    moderator = request_moderator()

    if request.method == 'GET':
        session_count = get_db().query(Session).count()

        current_ip4_str = get_request_ip4_str()

        return render_template('mod_site.html', site_config_config=site_config, session_count=session_count,
                               current_ip4_str=current_ip4_str)
    else:
        form = request.form

        if not check_csrf_token(form.get('token')):
            abort(400)

        try:
            config_service.save_from_form(moderator, site_config, site_config_row, form, 'mod_site_')
            flash('Site config updated')
            mod_log('site config updated')
            site_cache.invalidate_site_config()
        except ArgumentError as e:
            flash(str(e))

        return redirect(url_for('.mod_site'))


@mod.route('/mod_site/reset_sessions', methods=['POST'])
@mod_role_restrict(roles.ROLE_ADMIN)
@with_token()
def reset_sessions():
    mod_log('reset sessions')
    app.reset_sessions(get_db(), [session.session_id])
    return redirect(url_for('.mod_site'))


@mod.route('/stat')
@mod_role_restrict(roles.ROLE_ADMIN)
def mod_stat():
    db = get_db()

    stats = {
        'board count': db.query(Board).count(),
        'thread count': db.query(Thread).count(),
        'post count': db.query(Post).count(),
        'ban count': db.query(Ban).count(),
        'report count': db.query(Report).count(),
        'session count': db.query(Session).count(),
        'moderator count': db.query(Moderator).count(),
        'file count': db.query(File).count(),
        'config count': db.query(Config).count()
    }

    return render_template('stat.html', stats=stats)


@mod.route('/memcache_stat')
@mod_role_restrict(roles.ROLE_ADMIN)
def mod_memcache_stat():
    client = cache._client

    stats = client.get_stats()

    servers = []
    for stat in stats:
        s = 'server: ' + stat[0].decode('utf8') + '\n'
        t = []
        for k, v in stat[1].items():
            t.append((k.decode('utf8'), v.decode('utf8')))
        servers.append((s, t))

    return render_template('memcache_stat.html', stats=servers)
