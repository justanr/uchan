from sqlalchemy.orm import lazyload
from sqlalchemy.orm.exc import NoResultFound
from uchan import g
from uchan.lib import BadRequestError, ArgumentError
from uchan.lib.action_authorizer import PostAction, NoPermissionError, RequestBannedException
from uchan.lib.crypt_code_compat import generate_crypt_code
from uchan.lib.database import get_db
from uchan.lib.mod_log import mod_log
from uchan.lib.models import Post, Report, Thread, File
from uchan.lib.tasks.post_task import ManagePostDetails
from uchan.lib.utils import now, ip4_to_str


class PostsService:
    MAX_NAME_LENGTH = 35
    MAX_SUBJECT_LENGTH = 100
    MIN_PASSWORD_LENGTH = 5
    MAX_PASSWORD_LENGTH = 25
    MAX_TEXT_LENGTH = 2000
    MAX_TEXT_LINES = 25

    def handle_post_check(self, post_details):
        board, thread = self.get_board_thread(post_details)

        g.plugin_manager.execute_hook('on_handle_post_check', post_details)

        # Get moderator if mod_id was set
        moderator = None
        if post_details.mod_id is not None:
            moderator = g.moderator_service.find_moderator_id(post_details.mod_id)
            if moderator is None:
                raise Exception('Moderator not found')

        if thread is not None and thread.locked:
            raise ArgumentError('Thread is locked')

        g.action_authorizer.authorize_post_action(moderator, PostAction.POST_CREATE, post_details=post_details,
                                                  board=board, thread=thread)

        board_config = g.board_cache.find_board_config(board.name)
        if post_details.has_file and not board_config.get('file_posting_enabled'):
            raise ArgumentError('File posting is disabled')

        if not post_details.text or not post_details.text.strip():
            # Allow no text when an image is attached
            if not post_details.has_file:
                raise ArgumentError('No text')

        if post_details.text is not None:
            if len(post_details.text) > self.MAX_TEXT_LENGTH:
                raise ArgumentError('Text too long')

            if len(post_details.text.splitlines()) > self.MAX_TEXT_LINES:
                raise ArgumentError('Too many lines')

        if post_details.name is not None and len(post_details.name) > self.MAX_NAME_LENGTH:
            raise ArgumentError('Name too long')

        if post_details.password is not None:
            if len(post_details.password) < self.MIN_PASSWORD_LENGTH:
                raise ArgumentError(
                    'Password too short, at least {} characters required'.format(self.MIN_PASSWORD_LENGTH))

            if len(post_details.password) > self.MAX_PASSWORD_LENGTH:
                raise ArgumentError('Password too long, at most {} characters allowed'.format(self.MAX_PASSWORD_LENGTH))

    def handle_post(self, post_details):
        start_time = now()

        board, to_thread = self.get_board_thread(post_details)

        g.plugin_manager.execute_hook('on_handle_post', post_details)

        db = get_db()

        site_config = g.site_cache.find_site_config()
        default_name = site_config.get('default_name')
        board_config = g.board_cache.find_board_config(board.name)
        pages = board_config.get('pages')
        per_page = board_config.get('per_page')
        bump_limit = board_config.get('bump_limit')

        # Get moderator if mod_id was set
        moderator = None
        if post_details.mod_id is not None:
            moderator = g.moderator_service.find_moderator_id(post_details.mod_id)
            if moderator is None:
                raise Exception('Moderator not found')

        post = Post()
        if post_details.text is not None:
            post.text = post_details.text.strip()
        else:
            post.text = ''

        sage = False
        post.name = default_name
        if post_details.name is not None:
            stripped_name = post_details.name.strip()
            if stripped_name:
                if '#' in post_details.name:
                    raw_name, password = stripped_name.split('#', maxsplit=1)
                    raw_name = raw_name.replace('!', '')
                    if raw_name is not None and password:
                        # Styling is applied later
                        post.name = raw_name + ' !' + generate_crypt_code(password)
                elif stripped_name.lower() == 'sage':
                    sage = True
                    post.name = default_name
                else:
                    name = stripped_name.replace('!', '')
                    if name:
                        post.name = name

        if to_thread is None and post_details.subject is not None:
            post.subject = post_details.subject
        if post_details.password is not None:
            post.password = post_details.password
        post.date = now()
        post.ip4 = post_details.ip4

        if moderator is not None and g.moderator_service.moderates_board(moderator, board):
            post.moderator = moderator

        db.add(post)

        if post_details.uploaded_file is not None:
            self.attach_file(post, post_details.uploaded_file)

        if to_thread is None:
            board_name = board.name

            post.refno = 1

            thread = Thread()
            thread.last_modified = now()
            post.thread = thread
            thread.board = board
            db.add(thread)

            db.flush()
            thread_id = thread.id

            thread_ids_to_invalidate = self.purge_threads(board, pages, per_page)
            db.commit()

            insert_time = now() - start_time
            start_time = now()

            for thread_id_to_invalidate in thread_ids_to_invalidate:
                g.posts_cache.invalidate_thread_cache(thread_id_to_invalidate)
            g.posts_cache.invalidate_thread_cache(thread_id)
            g.posts_cache.invalidate_board_page_cache(board_name)

            cache_time = now() - start_time
            log = 'new thread /{}/{} ({})'.format(board_name, thread_id,
                                                  self.gather_statistics(insert_time, cache_time, post_details))
            mod_log(log, ip4_str=ip4_to_str(post_details.ip4))

            return board_name, thread.id, 1
        else:
            board_name = board.name
            thread_id = to_thread.id

            post.refno = 0
            # to_thread.posts += [post]
            post.thread = to_thread

            # Atomically update the refno counter
            to_thread.refno_counter = Thread.refno_counter + 1

            db.commit()

            # Set it to the post after the commit to make sure there aren't any duplicates
            post_refno = post.refno = to_thread.refno_counter
            post_id = post.id

            # Use the refno to avoid a count(*)
            if not sage and post_refno <= bump_limit:
                to_thread.last_modified = now()

            db.commit()

            insert_time = now() - start_time
            start_time = now()

            g.posts_cache.invalidate_thread_cache(thread_id)
            g.posts_cache.invalidate_board_page_cache(board_name)

            cache_time = now() - start_time
            log = 'new reply /{}/{}#{} (id: {} {})'.format(
                board_name, thread_id, post_refno, post_id,
                self.gather_statistics(insert_time, cache_time, post_details))
            mod_log(log, ip4_str=ip4_to_str(post_details.ip4))

            return board_name, thread_id, post_refno

    def gather_statistics(self, insert_time, cache_time, post_details):
        total = insert_time + cache_time + post_details.check_time
        file_time = ''
        if post_details.has_file:
            total += post_details.file_time
            file_time = 'file: {}ms, '.format(post_details.file_time)

        s = 'check: {}ms, {}db: {}ms, caches: {}ms, total: {}ms'
        return s.format(post_details.check_time, file_time, insert_time, cache_time, total)

    def get_board_thread(self, post_details):
        board = g.board_service.find_board(post_details.board_name)
        if not board:
            raise ArgumentError('Board not found')

        thread = None
        if post_details.thread_id is not None:
            thread = g.posts_service.find_thread(post_details.thread_id)
            if thread is None:
                raise ArgumentError('Thread not found')

        return board, thread

    def attach_file(self, post, uploaded_file):
        file = File()
        file.location = uploaded_file.location
        file.thumbnail_location = uploaded_file.thumbnail_location
        file.original_name = uploaded_file.original_name
        file.post = post
        file.width = uploaded_file.width
        file.height = uploaded_file.height
        file.size = uploaded_file.size
        file.thumbnail_width = uploaded_file.thumbnail_width
        file.thumbnail_height = uploaded_file.thumbnail_height
        db = get_db()
        db.add(file)

    def handle_manage_post(self, details):
        thread = self.find_thread(details.thread_id)
        if thread is None:
            raise BadRequestError('Thread not found')

        post = self.find_post(details.post_id)

        board = thread.board

        # Get moderator if mod_id was set
        moderator = None
        moderator_name = None
        if details.mod_id is not None:
            moderator = g.moderator_service.find_moderator_id(details.mod_id)
            if moderator is None:
                raise Exception('Moderator not found')
            else:
                moderator_name = moderator.username

        # You cannot manage when you are banned
        if g.ban_service.is_request_banned(details.ip4, board):
            raise RequestBannedException()

        if details.mode == ManagePostDetails.DELETE or details.mode == ManagePostDetails.REPORT:
            if post is None:
                if not details.post_id:
                    raise BadRequestError('No post selected')
                else:
                    raise BadRequestError('Post not found')

            if details.mode == ManagePostDetails.DELETE:
                try:
                    g.action_authorizer.authorize_post_action(moderator, PostAction.POST_DELETE, post, details)
                    mod_log('post {} delete'.format(details.post_id), ip4_str=ip4_to_str(details.ip4),
                            moderator_name=moderator_name)
                    self.delete_post(post)
                except NoPermissionError as e:
                    mod_log('post {} delete failed, {}'.format(details.post_id, str(e)),
                            ip4_str=ip4_to_str(details.ip4), moderator_name=moderator_name)
                    raise BadRequestError('Password invalid')
            elif details.mode == ManagePostDetails.REPORT:
                g.action_authorizer.authorize_post_action(moderator, PostAction.POST_REPORT, post, details)
                report = Report(post_id=post.id)
                mod_log('post {} reported'.format(post.id), ip4_str=ip4_to_str(details.ip4),
                        moderator_name=moderator_name)
                g.report_service.add_report(report)
        elif details.mode == ManagePostDetails.TOGGLE_STICKY or details.mode == ManagePostDetails.TOGGLE_LOCKED:
            if moderator is None:
                raise BadRequestError('Moderator not found')

            if details.mode == ManagePostDetails.TOGGLE_STICKY:
                g.action_authorizer.authorize_post_action(moderator, PostAction.THREAD_STICKY_TOGGLE, board=board)

                mod_log('sticky on /{}/{} {}'.format(
                    thread.board.name, thread.id, 'disabled' if thread.sticky else 'enabled'),
                    ip4_str=ip4_to_str(details.ip4), moderator_name=moderator_name)
                self.toggle_thread_sticky(thread)
            elif details.mode == ManagePostDetails.TOGGLE_LOCKED:
                g.action_authorizer.authorize_post_action(moderator, PostAction.THREAD_LOCKED_TOGGLE, board=board)

                mod_log('lock on /{}/{} {}'.format(
                    thread.board.name, thread.id, 'disabled' if thread.locked else 'enabled'),
                    ip4_str=ip4_to_str(details.ip4), moderator_name=moderator_name)
                self.toggle_thread_locked(thread)
        else:
            raise Exception()

    def find_thread(self, thread_id, include_posts=False):
        try:
            q = get_db().query(Thread)
            if include_posts:
                q = q.options(lazyload('posts'))
            thread = q.filter_by(id=thread_id).one()

            if include_posts:
                # The thread and posts query are done separately
                # And thus there is a possibility that the second query returns empty data
                # when another transaction deletes the thread
                # Account for this by just returning None as if the thread didn't exist
                if not thread.posts:
                    return None

            return thread
        except NoResultFound:
            return None

    def toggle_thread_sticky(self, thread):
        thread.sticky = not thread.sticky
        db = get_db()
        db.commit()

        # Invalidate caches
        g.posts_cache.invalidate_thread_cache(thread.id)
        g.posts_cache.invalidate_board_page_cache(thread.board.name)

    def toggle_thread_locked(self, thread):
        thread.locked = not thread.locked
        db = get_db()
        db.commit()

        # Invalidate caches
        g.posts_cache.invalidate_thread_cache(thread.id)
        g.posts_cache.invalidate_board_page_cache(thread.board.name)

    def find_post(self, post_id):
        try:
            return get_db().query(Post).filter_by(id=post_id).one()
        except NoResultFound:
            return None

    def delete_file(self, post):
        if post.file is None:
            raise ArgumentError('No file on post')

        thread_id = post.thread.id
        board_name = post.thread.board.name
        db = get_db()
        # The file_service listens to deletes and will delete it from the cdn
        db.delete(post.file)
        db.commit()

        # Invalidate caches
        g.posts_cache.invalidate_thread_cache(thread_id)
        g.posts_cache.invalidate_board_page_cache(board_name)

    def delete_post(self, post):
        if post.refno == 1:
            self.delete_thread(post.thread)
        else:
            thread_id = post.thread.id
            board_name = post.thread.board.name
            db = get_db()
            db.delete(post)
            db.commit()

            # Invalidate caches
            g.posts_cache.invalidate_thread_cache(thread_id)
            g.posts_cache.invalidate_board_page_cache(board_name)

    def delete_thread(self, thread):
        thread_id = thread.id
        board_name = thread.board.name

        db = get_db()
        db.delete(thread)
        db.commit()

        # Invalidate caches
        g.posts_cache.invalidate_thread_cache(thread_id)
        g.posts_cache.invalidate_board_page_cache(board_name)

    def purge_threads(self, board, pages, per_page):
        max = (per_page * pages) - 1

        db = get_db()

        thread_ids_to_invalidate = []
        overflowed_threads = db.query(Thread).order_by(Thread.last_modified.desc()).filter_by(board_id=board.id)[max:]
        for overflowed_thread in overflowed_threads:
            thread_id = overflowed_thread.id
            db.delete(overflowed_thread)
            thread_ids_to_invalidate.append(thread_id)
        return thread_ids_to_invalidate
