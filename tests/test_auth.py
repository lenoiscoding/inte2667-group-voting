def test_login_wrong_password(client):
    response = client.post(
        "/auth/login",
        data={
            "username": "testadmin",
            "password": "WrongPassword123!"
        },
        follow_redirects=True
    )

    assert response.status_code == 200
    assert b"Invalid" in response.data or b"incorrect" in response.data.lower()