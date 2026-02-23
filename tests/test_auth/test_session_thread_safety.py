"""Tests for SessionStore and UserStore async concurrency safety.

Verifies that concurrent asyncio tasks accessing SessionStore and UserStore
don't corrupt internal dictionaries or indexes.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from temper_ai.auth.models import Session, User
from temper_ai.auth.session import SessionStore, UserStore


def _make_user(idx: int) -> User:
    """Create a test user with a unique index."""
    return User(
        user_id=f"user-{idx}",
        email=f"user{idx}@example.com",
        name=f"User {idx}",
        oauth_provider="google",
        oauth_subject=f"google-{idx}",
    )


class TestSessionStoreConcurrency:
    """Verify SessionStore is safe under concurrent async access."""

    @pytest.mark.asyncio
    async def test_concurrent_session_creation_50_tasks(self):
        """50 concurrent tasks creating sessions all succeed."""
        store = SessionStore()
        users = [_make_user(i) for i in range(50)]

        async def create(user):
            return await store.create_session(user)

        sessions = await asyncio.gather(*[create(u) for u in users])

        assert len(sessions) == 50
        # All sessions should be in the store
        assert len(store._sessions) == 50
        # All session IDs should be unique
        ids = [s.session_id for s in sessions]
        assert len(set(ids)) == 50

    @pytest.mark.asyncio
    async def test_concurrent_session_creation_and_deletion(self):
        """Sessions created and deleted concurrently maintain consistency."""
        store = SessionStore()
        users = [_make_user(i) for i in range(20)]

        # Create 20 sessions first
        sessions = []
        for u in users:
            s = await store.create_session(u)
            sessions.append(s)

        assert len(store._sessions) == 20

        # Concurrently delete first 10 and create 10 more
        async def delete(session_id):
            return await store.delete_session(session_id)

        async def create(user):
            return await store.create_session(user)

        delete_tasks = [delete(s.session_id) for s in sessions[:10]]
        create_tasks = [create(_make_user(20 + i)) for i in range(10)]

        results = await asyncio.gather(*(delete_tasks + create_tasks))

        # 10 deletes should all succeed
        delete_results = results[:10]
        assert all(r is True for r in delete_results)

        # Should have 20 sessions (20 original - 10 deleted + 10 new)
        assert len(store._sessions) == 20

    @pytest.mark.asyncio
    async def test_concurrent_get_session(self):
        """Concurrent reads don't interfere with each other."""
        store = SessionStore()
        user = _make_user(0)
        session = await store.create_session(user)

        async def get():
            return await store.get_session(session.session_id)

        results = await asyncio.gather(*[get() for _ in range(50)])
        assert all(r is not None for r in results)
        assert all(r.session_id == session.session_id for r in results)

    @pytest.mark.asyncio
    async def test_concurrent_cleanup_expired(self):
        """Concurrent cleanup_expired calls don't double-delete or error."""
        store = SessionStore()
        user = _make_user(0)

        # Create sessions that are already expired
        for i in range(10):
            session = await store.create_session(user, session_max_age=0)
            # Force expiration by overriding expires_at
            async with store._lock:
                store._sessions[session.session_id] = Session(
                    session_id=session.session_id,
                    user_id=user.user_id,
                    email=user.email,
                    name=user.name,
                    expires_at=datetime.now(UTC) - timedelta(seconds=10),
                )

        # Also create 5 valid sessions
        valid_sessions = []
        for i in range(5):
            s = await store.create_session(_make_user(100 + i))
            valid_sessions.append(s)

        assert len(store._sessions) == 15

        # Run multiple concurrent cleanups
        await asyncio.gather(*[store.cleanup_expired() for _ in range(10)])

        # Only valid sessions should remain
        assert len(store._sessions) == 5
        for s in valid_sessions:
            result = await store.get_session(s.session_id)
            assert result is not None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_session(self):
        """Deleting a non-existent session returns False, no error."""
        store = SessionStore()
        result = await store.delete_session("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_expired_session_cleans_up(self):
        """Getting an expired session removes it from the store."""
        store = SessionStore()
        user = _make_user(0)
        session = await store.create_session(user, session_max_age=0)

        # Force expiration
        async with store._lock:
            store._sessions[session.session_id] = Session(
                session_id=session.session_id,
                user_id=user.user_id,
                email=user.email,
                name=user.name,
                expires_at=datetime.now(UTC) - timedelta(seconds=10),
            )

        result = await store.get_session(session.session_id)
        assert result is None
        assert session.session_id not in store._sessions


class TestUserStoreConcurrency:
    """Verify UserStore is safe under concurrent async access."""

    @pytest.mark.asyncio
    async def test_concurrent_user_creation_50_tasks(self):
        """50 concurrent tasks creating unique users all succeed."""
        store = UserStore()

        async def create(idx):
            return await store.create_or_update_user(
                user_id=f"user-{idx}",
                email=f"user{idx}@example.com",
                name=f"User {idx}",
                provider="google",
                oauth_subject=f"google-{idx}",
            )

        users = await asyncio.gather(*[create(i) for i in range(50)])

        assert len(users) == 50
        assert len(store._users) == 50
        assert len(store._emails) == 50
        assert len(store._oauth_subjects) == 50

        # Verify all indexes are consistent
        for i in range(50):
            user = await store.get_user_by_id(f"user-{i}")
            assert user is not None
            assert user.email == f"user{i}@example.com"

            user_by_email = await store.get_user_by_email(f"user{i}@example.com")
            assert user_by_email is not None
            assert user_by_email.user_id == f"user-{i}"

            user_by_oauth = await store.get_user_by_oauth("google", f"google-{i}")
            assert user_by_oauth is not None
            assert user_by_oauth.user_id == f"user-{i}"

    @pytest.mark.asyncio
    async def test_concurrent_duplicate_email_creation(self):
        """Concurrent creates with same email don't create duplicates."""
        store = UserStore()

        # First create the user
        await store.create_or_update_user(
            user_id="user-original",
            email="shared@example.com",
            name="Original",
            provider="google",
            oauth_subject="google-original",
        )

        # Now 20 concurrent updates to the same email
        async def update(idx):
            return await store.create_or_update_user(
                user_id=f"user-{idx}",  # Would-be new ID (ignored since email exists)
                email="shared@example.com",
                name=f"Name {idx}",
                provider="google",
                oauth_subject=f"google-{idx}",
            )

        results = await asyncio.gather(*[update(i) for i in range(20)])

        # All results should reference the same original user_id
        assert all(r.user_id == "user-original" for r in results)
        # Only one user should exist
        assert len(store._users) == 1
        assert len(store._emails) == 1

    @pytest.mark.asyncio
    async def test_index_consistency_after_concurrent_operations(self):
        """All three indexes remain consistent after concurrent ops."""
        store = UserStore()

        async def create(idx):
            return await store.create_or_update_user(
                user_id=f"user-{idx}",
                email=f"user{idx}@example.com",
                name=f"User {idx}",
                provider="google",
                oauth_subject=f"google-{idx}",
            )

        await asyncio.gather(*[create(i) for i in range(30)])

        # Verify _emails index maps correctly to _users
        for email, user_id in store._emails.items():
            assert (
                user_id in store._users
            ), f"Email index points to missing user: {email} -> {user_id}"
            assert store._users[user_id].email == email

        # Verify _oauth_subjects index maps correctly to _users
        for key, user_id in store._oauth_subjects.items():
            assert (
                user_id in store._users
            ), f"OAuth index points to missing user: {key} -> {user_id}"

    @pytest.mark.asyncio
    async def test_concurrent_reads_during_writes(self):
        """Reads during concurrent writes return consistent results."""
        store = UserStore()

        # Pre-populate some users
        for i in range(10):
            await store.create_or_update_user(
                user_id=f"user-{i}",
                email=f"user{i}@example.com",
                name=f"User {i}",
                provider="google",
                oauth_subject=f"google-{i}",
            )

        errors = []

        async def reader():
            for _ in range(20):
                for i in range(10):
                    user = await store.get_user_by_email(f"user{i}@example.com")
                    if user is not None and user.user_id != f"user-{i}":
                        errors.append(
                            f"Inconsistent: email user{i}@example.com -> user_id {user.user_id}"
                        )
                await asyncio.sleep(0)

        async def writer():
            for i in range(10, 30):
                await store.create_or_update_user(
                    user_id=f"user-{i}",
                    email=f"user{i}@example.com",
                    name=f"User {i}",
                    provider="google",
                    oauth_subject=f"google-{i}",
                )
                await asyncio.sleep(0)

        await asyncio.gather(reader(), reader(), writer())

        assert not errors, f"Index consistency errors: {errors}"

    @pytest.mark.asyncio
    async def test_get_user_by_id_single_dict(self):
        """get_user_by_id works without lock (single dict read)."""
        store = UserStore()
        await store.create_or_update_user(
            user_id="user-1",
            email="user1@example.com",
            name="User 1",
            provider="google",
            oauth_subject="google-1",
        )

        # 50 concurrent reads by ID
        async def read():
            return await store.get_user_by_id("user-1")

        results = await asyncio.gather(*[read() for _ in range(50)])
        assert all(r is not None for r in results)
        assert all(r.user_id == "user-1" for r in results)


class TestLockIsolation:
    """Verify SessionStore and UserStore locks are independent."""

    @pytest.mark.asyncio
    async def test_no_cross_store_deadlock(self):
        """Concurrent operations on both stores don't deadlock."""
        session_store = SessionStore()
        user_store = UserStore()

        async def session_ops(idx):
            user = _make_user(idx)
            session = await session_store.create_session(user)
            await session_store.get_session(session.session_id)
            await session_store.delete_session(session.session_id)

        async def user_ops(idx):
            await user_store.create_or_update_user(
                user_id=f"user-{idx}",
                email=f"user{idx}@example.com",
                name=f"User {idx}",
                provider="google",
                oauth_subject=f"google-{idx}",
            )
            await user_store.get_user_by_email(f"user{idx}@example.com")

        # Run session and user operations concurrently
        tasks = []
        for i in range(20):
            tasks.append(session_ops(i))
            tasks.append(user_ops(i))

        # Should complete without deadlock (timeout would indicate deadlock)
        results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=10.0)
        assert len(results) == 40  # 20 session_ops + 20 user_ops all completed
