"""Tests for lockin.expand."""

from lockin.expand import expand


def test_reddit_includes_old():
    names = expand(["reddit.com"])
    assert "reddit.com" in names
    assert "old.reddit.com" in names
    assert "new.reddit.com" in names
    assert "i.reddit.com" in names
    assert "m.reddit.com" in names


def test_youtube_includes_youtu_be():
    names = expand(["youtube.com"])
    assert "youtu.be" in names
    assert "m.youtube.com" in names


def test_twitter_includes_x():
    names = expand(["twitter.com"])
    assert "x.com" in names
    assert "twitter.com" in names


def test_no_url_shorteners():
    names = expand(["twitter.com", "linkedin.com"])
    assert "t.co" not in names
    assert "lnkd.in" not in names


def test_idempotent():
    once = expand(["reddit.com", "youtube.com"])
    twice = expand(once)
    assert once == twice


def test_strips_www():
    assert "facebook.com" in expand(["www.facebook.com"])
    assert "fb.com" in expand(["www.facebook.com"])
