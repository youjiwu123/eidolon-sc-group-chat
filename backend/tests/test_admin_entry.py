"""Entering the admin console: admins are the users who sign in with an identity the
deployer lists in `EIDOLON_ADMINS`. Everyone else, signed in or not, finds no admin
console at all (404), and without the list there is none for anyone."""

from dataclasses import replace

import httpx
import pytest

from eidolon.config import Settings, admins_from_env
from tests.conftest import (
    Admin,
    ClientFactory,
    agree_to_terms,
    github_identity,
    google_identity,
    sign_in_with,
)
from tests.fakes import FakeIdentityProvider, FakeLLM


async def enters(client: httpx.AsyncClient) -> bool:
    """Whether the client finds the admin console, which then greets them by name."""
    res = await client.get("/api/admin")
    assert res.status_code in (200, 404), res.text
    return res.status_code == 200


async def is_admin(client: httpx.AsyncClient) -> bool:
    res = await client.get("/api/account")
    assert res.status_code == 200, res.text
    return res.json()["is_admin"]


async def test_admins_enter_by_any_identity_listed_and_no_one_else_does(
    make_client: ClientFactory,
    settings: Settings,
    github: FakeIdentityProvider,
    google: FakeIdentityProvider,
):
    settings = replace(settings, admins=frozenset({("github", "1001"), ("google", "g-2002")}))
    by_github = make_client(FakeLLM(), user=None, settings=settings)
    await sign_in_with(by_github, github, github_identity("1001", name="octo"))
    await agree_to_terms(by_github)
    # Google's identity is listed, though the user first signed in with GitHub's.
    linked = make_client(FakeLLM(), user=None, settings=settings)
    await sign_in_with(linked, github, github_identity("3003", name="linked"))
    await agree_to_terms(linked)
    await sign_in_with(linked, google, google_identity("g-2002"), link=True)
    # The subject listed for GitHub is no one's at Google.
    other = make_client(FakeLLM(), user=None, settings=settings)
    await sign_in_with(other, google, google_identity("1001", email="other@example.com"))
    await agree_to_terms(other)
    nobody = make_client(FakeLLM(), user=None, settings=settings)

    assert await enters(by_github) and await is_admin(by_github)
    assert (await by_github.get("/api/admin")).json() == {"name": "octo"}
    assert await enters(linked) and await is_admin(linked)
    assert not await enters(other) and not await is_admin(other)
    assert not await enters(nobody)


async def test_a_developer_login_the_list_names_is_an_admin(
    make_client: ClientFactory, settings: Settings
):
    """没有配 OAuth 的本地部署也要有管理员：开发者登录会给账号记一条 `github:<名字>` 的
    身份，`EIDOLON_ADMINS` 里写同一个名字就算（只开了 `EIDOLON_DEV_LOGIN` 时才有这条登录）。"""
    settings = replace(settings, admins=frozenset({("github", "producer")}))

    listed = make_client(FakeLLM(), user=None, settings=settings)
    assert (await listed.post("/api/auth/dev-login", json={"name": "producer"})).status_code == 204
    await agree_to_terms(listed)

    assert await enters(listed) and await is_admin(listed)
    methods = (await listed.get("/api/account")).json()["sign_in_methods"]
    assert [m["provider"] for m in methods] == ["github"]
    # 名单里没有的名字登录进来，照旧什么后台也看不到。
    other = make_client(FakeLLM(), user=None, settings=settings)
    assert (await other.post("/api/auth/dev-login", json={"name": "someone"})).status_code == 204
    await agree_to_terms(other)
    assert not await enters(other) and not await is_admin(other)


async def test_an_admin_who_has_not_agreed_to_the_terms_finds_no_admin_console(
    make_client: ClientFactory, settings: Settings, github: FakeIdentityProvider
):
    settings = replace(settings, admins=frozenset({("github", "1001")}))
    client = make_client(FakeLLM(), user=None, settings=settings)
    await sign_in_with(client, github, github_identity("1001"))

    assert not await enters(client)

    await agree_to_terms(client)
    assert await enters(client)


async def test_without_the_list_there_is_no_admin_console(
    make_client: ClientFactory, github: FakeIdentityProvider
):
    client = make_client(FakeLLM(), user=None)
    await sign_in_with(client, github, github_identity("1001"))
    await agree_to_terms(client)

    assert not await enters(client)


async def test_a_banned_admin_finds_no_admin_console(
    make_client: ClientFactory, settings: Settings, admin: Admin, github: FakeIdentityProvider
):
    settings = replace(settings, admins=frozenset({("github", "1001")}))
    client = make_client(FakeLLM(), user=None, settings=settings)
    await sign_in_with(client, github, github_identity("1001", name="octo"))
    await agree_to_terms(client)
    [line] = admin.run("user", "list").splitlines()

    admin.run("user", "ban", line.split("	")[0])

    assert not await enters(client)


def test_the_list_names_identities_by_provider_and_subject(monkeypatch: pytest.MonkeyPatch):
    assert admins_from_env() == frozenset()

    monkeypatch.setenv("EIDOLON_ADMINS", " github:1001, google:1234567890 ,")
    assert admins_from_env() == frozenset({("github", "1001"), ("google", "1234567890")})

    for bad, named in [("github:1001,octo", "octo"), ("github:", "github:"), ("gitlab:7", "gitlab")]:
        monkeypatch.setenv("EIDOLON_ADMINS", bad)
        with pytest.raises(RuntimeError, match=named):
            admins_from_env()
