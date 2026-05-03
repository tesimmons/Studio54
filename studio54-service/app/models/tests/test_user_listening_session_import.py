def test_import():
    from app.models.user_listening_session import UserListeningSession
    assert UserListeningSession.__tablename__ == "user_listening_sessions"
