from click.testing import CliRunner
from unittest.mock import patch
from pathlib import Path
from functools import partial

import pytest
from dflock import utils
from dflock.main import (
    cli_group, Delta, Commit, parse_plan, ParsingError, PlanError,
    reconstruct_tree, write_plan, get_local_commits, render_plan,
    build_tree, read_config
)

UPSTREAM = "upstream"
LOCAL = "local"
REMOTE = ""
BRANCH_TEMPLATE = "test/{}"
ANCHOR_COMMIT = "first"
TEST_CONFIG = f"""[dflock]
upstream={UPSTREAM}
local={LOCAL}
remote={REMOTE}
branch-template={BRANCH_TEMPLATE}
"""


@pytest.fixture(autouse=True)
def configuration(tmp_path):
    test_config_path = tmp_path / ".dflock"

    def new_read_config(ctx, cmd, path):
        return read_config(ctx, cmd, test_config_path)
    with open(test_config_path, "w") as f:
        f.write(TEST_CONFIG)
    with patch("dflock.main.read_config", new_read_config):
        yield


@pytest.fixture()
def git_repository(tmp_path):
    new_run = partial(utils.run, cwd=tmp_path)
    with patch("dflock.utils.run", new_run):
        utils.run("init")
        utils.run("config", "user.email", "you@example.com")
        utils.run("config", "user.name", "Your Name")
        yield Path(tmp_path)


@pytest.fixture()
def runner():
    yield CliRunner()


@pytest.fixture()
def upstream(git_repository):
    utils.run(*(f"checkout -b {UPSTREAM}".split()), cwd=git_repository)
    utils.run(*("checkout -".split()), cwd=git_repository)


@pytest.fixture()
def local(git_repository):
    utils.run(*(f"checkout -b {LOCAL}".split()), cwd=git_repository)
    utils.run(*("checkout -".split()), cwd=git_repository)


@pytest.fixture()
def commit_a(git_repository):
    with open(git_repository / "a", "w") as f:
        f.write("a")
    utils.run(*("add a".split()), cwd=git_repository)
    utils.run(*("commit -m a".split()), cwd=git_repository)
    return utils.run(*("rev-parse HEAD".split()))


@pytest.fixture()
def commit_b(git_repository):
    with open(git_repository / "b", "w") as f:
        f.write("")
    utils.run(*("add .".split()), cwd=git_repository)
    utils.run(*("commit -m b".split()), cwd=git_repository)
    return utils.run(*("rev-parse HEAD".split()))


@pytest.fixture()
def commit_c(git_repository):
    with open(git_repository / "c", "w") as f:
        f.write("")
    utils.run(*("add .".split()), cwd=git_repository)
    utils.run(*("commit -m c".split()), cwd=git_repository)
    return utils.run(*("rev-parse HEAD".split()))


@pytest.fixture()
def local_commits():
    commits = [
        Commit("0", "a"), Commit("1", "b"), Commit("2", "c"), Commit("3", "d")
    ]
    with patch("dflock.main.get_local_commits", return_value=commits):
        yield commits


@pytest.fixture
def commit(git_repository):
    def _commit(files, message):
        for path, contents in files.items():
            with open(git_repository / path, "w") as f:
                f.write(contents)
            utils.run("add", path)
        utils.run("commit", "-m", message)
        return utils.run("rev-parse", "HEAD")
    return _commit


@pytest.fixture
def create_branch(git_repository):
    def _create_branch(name):
        utils.run("checkout", "-b", name, cwd=git_repository)
        utils.run("checkout", "-", cwd=git_repository)
    return _create_branch


@pytest.fixture
def checkout(git_repository):
    def _checkout(name):
        utils.run("checkout", name, cwd=git_repository)
    return _checkout


def test_parse_plan__syntax_errors(local_commits):
    config_args = [LOCAL, UPSTREAM, ANCHOR_COMMIT, BRANCH_TEMPLATE]
    with pytest.raises(ParsingError):
        parse_plan("s 0 a\na 1 b\ns 2 v", *config_args) == {}
    with pytest.raises(ParsingError):
        parse_plan("b@s 0 a", *config_args) == {}
    with pytest.raises(ParsingError):
        parse_plan("s 0 a\nb\ns 2 v", *config_args) == {}


def test_parse_plan__illegal_plans(local_commits):
    config_args = [LOCAL, UPSTREAM, ANCHOR_COMMIT, BRANCH_TEMPLATE]
    with pytest.raises(PlanError, match="cannot match"):
        # Unrecognized commit
        parse_plan("s 0 a\nb1 a\ns 2 v", *config_args) == {}
    with pytest.raises(PlanError, match="cannot match"):
        # Out of order commits
        parse_plan("b 1 a\nb 0 foo", *config_args) == {}
    with pytest.raises(PlanError, match="invalid target"):
        # Non contiguous commits in branch
        parse_plan("b 0 a\nb1@b 1 foo\nb  2 v", *config_args) == {}
    with pytest.raises(PlanError, match="invalid target"):
        # Incorrect target
        parse_plan("b@b1 0 a\nb1 1 foo", *config_args) == {}
    with pytest.raises(PlanError, match="multiple targets"):
        # Conflicting targets
        parse_plan("b 0 a\nb1 1\nb2@b 2 v\nb2@b1 3", *config_args) == {}
    with pytest.raises(PlanError, match="invalid target"):
        # "Crossing" branches
        parse_plan("b 0 a\nb1@b 1 foo\nb2 2 v", *config_args) == {}


@pytest.mark.parametrize("anchor_commit", ["first", "last"])
def test_parse_plan__legal_plans(local_commits, anchor_commit):
    config_args = [anchor_commit, UPSTREAM, BRANCH_TEMPLATE]
    config_args_parse = [LOCAL, UPSTREAM, anchor_commit, BRANCH_TEMPLATE]
    a, b, c, d = local_commits
    # Equivalent plans
    delta = Delta([c], None, *config_args)
    tree = {delta.branch_name: delta}
    v0 = parse_plan("s 0 a\ns 1 b\nb0 2 v", *config_args_parse)
    v1 = parse_plan("s 0 a\nb0 2 v", *config_args_parse)
    v2 = parse_plan("b0 2 v", *config_args_parse)
    v3 = parse_plan("b 2 v", *config_args_parse)
    v4 = parse_plan("b 2", *config_args_parse)
    assert v0 == v1 == v2 == v3 == v4 == tree
    # Empty plans
    assert parse_plan("", *config_args_parse) == {}
    assert parse_plan("s 0 a\ns 1 b\ns 2 v", *config_args_parse) == {}
    # Optional target specifications
    b0 = Delta([a], None, *config_args)
    b1 = Delta([b, c], b0, *config_args)
    tree = {d.branch_name: d for d in [b0, b1]}
    variant_1 = parse_plan("b 0 a\nb1@b 1 b\nb1 2 v", *config_args_parse)
    variant_2 = parse_plan("b 0 a\nb1 1 b\nb1@b 2 v", *config_args_parse)
    variant_3 = parse_plan("b 0 a\nb1@b 1 b\nb1@b 2 v", *config_args_parse)
    variant_4 = parse_plan("b 0 a\nb1@ 1 b\nb1@b 2 v", *config_args_parse)
    assert tree == variant_1 == variant_2 == variant_3 == variant_4
    b0 = Delta([a, c], None, *config_args)
    tree = {b0.branch_name: b0}
    assert parse_plan("b 0 a\ns 1 foo\nb 2 v", *config_args_parse) == tree
    b0 = Delta([a], None, *config_args)
    b1 = Delta([b], b0, *config_args)
    b2 = Delta([c], b1, *config_args)
    tree = {d.branch_name: d for d in [b0, b1, b2]}
    variant_1 = parse_plan(
        "b0 0 a\nb1@b0 1 foo\nb2@b1 2 v", *config_args_parse
    )
    variant_2 = parse_plan("b 0 a\nb1@b 1 foo\nb2@1 2 v", *config_args_parse)
    assert tree == variant_1
    assert tree == variant_2


@pytest.fixture
def independent_commits(commit, create_branch):
    commit(dict(x="x"), "0")
    create_branch(UPSTREAM)
    commit(dict(a="a"), "1")
    commit(dict(b="b"), "2")
    commit(dict(c="c"), "3")
    commit(dict(d="d"), "4")
    create_branch(LOCAL)
    return get_local_commits(LOCAL, UPSTREAM)


@pytest.fixture
def serially_dependent_commits(commit, create_branch):
    commit(dict(a="a"), "0")
    create_branch(UPSTREAM)
    commit(dict(a="b"), "1")
    commit(dict(a="c"), "2")
    commit(dict(a="d"), "3")
    commit(dict(a="e"), "4")
    create_branch(LOCAL)
    return get_local_commits(LOCAL, UPSTREAM)


@pytest.fixture
def dag_commits(commit, create_branch):
    commit(dict(a="a"), "0")
    create_branch(UPSTREAM)
    commit(dict(a="b"), "1")
    commit(dict(a="c"), "2")
    commit(dict(b="a"), "3")
    commit(dict(a="d"), "4")
    create_branch(LOCAL)
    return get_local_commits(LOCAL, UPSTREAM)


@pytest.mark.parametrize("anchor_commit", ["first", "last"])
def test_reconstruct_tree__anchor_commit(anchor_commit, dag_commits):
    c1, c2, c3, c4 = dag_commits
    plan = (
        f"b0 {c1.short_str}\n"
        f"b0 {c2.short_str}\n"
        f"b1 {c3.short_str}\n"
        f"b2@b0 {c4.short_str}"
    )
    config_args = [LOCAL, UPSTREAM, anchor_commit, BRANCH_TEMPLATE]
    tree = parse_plan(plan, *config_args)
    write_plan(tree)
    reconstructed_tree = reconstruct_tree(*config_args)
    b = Delta([c1, c2], None, anchor_commit, UPSTREAM, BRANCH_TEMPLATE)
    b1 = Delta([c3], None, anchor_commit, UPSTREAM, BRANCH_TEMPLATE)
    b2 = Delta([c4], b, anchor_commit, UPSTREAM, BRANCH_TEMPLATE)
    if anchor_commit == "first":
        assert reconstructed_tree == {
            c1.get_branch_name(BRANCH_TEMPLATE): b,
            c3.get_branch_name(BRANCH_TEMPLATE): b1,
            c4.get_branch_name(BRANCH_TEMPLATE): b2,
        }
    else:
        assert reconstructed_tree == {
            c2.get_branch_name(BRANCH_TEMPLATE): b,
            c3.get_branch_name(BRANCH_TEMPLATE): b1,
            c4.get_branch_name(BRANCH_TEMPLATE): b2,
        }


@pytest.mark.parametrize("anchor_commit", ["first", "last"])
def test_reconstruct_tree(dag_commits, anchor_commit):
    c1, c2, c3, c4 = dag_commits
    plan = (
        f"b0 {c1.short_str}\n"
        f"b0 {c2.short_str}\n"
        f"b1 {c3.short_str}\n"
        f"b2@b0 {c4.short_str}"
    )
    config_args = [LOCAL, UPSTREAM, ANCHOR_COMMIT, BRANCH_TEMPLATE]
    tree = parse_plan(plan, *config_args)
    write_plan(tree)
    config_args = [LOCAL, UPSTREAM, ANCHOR_COMMIT, BRANCH_TEMPLATE]
    reconstructed_tree = reconstruct_tree(*config_args)
    reconstructed_plan = render_plan(reconstructed_tree, LOCAL, UPSTREAM)
    assert reconstructed_plan == plan
    b0 = Delta([c1, c2], None, ANCHOR_COMMIT, UPSTREAM, BRANCH_TEMPLATE)
    b1 = Delta([c3], None, ANCHOR_COMMIT, UPSTREAM, BRANCH_TEMPLATE)
    b2 = Delta([c4], b0, ANCHOR_COMMIT, UPSTREAM, BRANCH_TEMPLATE)
    assert reconstructed_tree == {
        b0.branch_name: b0,
        b1.branch_name: b1,
        b2.branch_name: b2,
    }


@pytest.mark.parametrize("anchor_commit", ["first", "last"])
def test_reconstruct_tree_stacked(serially_dependent_commits, anchor_commit):
    c1, c2, c3, c4 = serially_dependent_commits
    tree = build_tree(
        LOCAL, UPSTREAM, ANCHOR_COMMIT, BRANCH_TEMPLATE, stack=True
    )
    write_plan(tree)
    config_args = [LOCAL, UPSTREAM, ANCHOR_COMMIT, BRANCH_TEMPLATE]
    reconstructed_tree = reconstruct_tree(*config_args)
    reconstructed_plan = render_plan(reconstructed_tree, LOCAL, UPSTREAM)
    plan = (
        f"b0 {c1.short_str}\n"
        f"b1@b0 {c2.short_str}\n"
        f"b2@b1 {c3.short_str}\n"
        f"b3@b2 {c4.short_str}"
    )
    assert reconstructed_plan == plan
    b0 = Delta([c1], None, ANCHOR_COMMIT, UPSTREAM, BRANCH_TEMPLATE)
    b1 = Delta([c2], b0, ANCHOR_COMMIT, UPSTREAM, BRANCH_TEMPLATE)
    b2 = Delta([c3], b1, ANCHOR_COMMIT, UPSTREAM, BRANCH_TEMPLATE)
    b3 = Delta([c4], b2, ANCHOR_COMMIT, UPSTREAM, BRANCH_TEMPLATE)
    assert reconstructed_tree == {
        b0.branch_name: b0,
        b1.branch_name: b1,
        b2.branch_name: b2,
        b3.branch_name: b3,
    }


def test_plan__not_a_git_repo(runner):
    with runner.isolated_filesystem():
        result = runner.invoke(cli_group, ["plan"])
    assert result.exit_code == 1
    assert (
        "Error: No git repository detected"
        in result.output
    )


@pytest.mark.parametrize("anchor_commit", ["first", "last"])
def test_reconstruct_tree_independent(independent_commits, anchor_commit):
    c1, c2, c3, c4 = independent_commits
    tree = build_tree(
        LOCAL, UPSTREAM, ANCHOR_COMMIT, BRANCH_TEMPLATE, stack=False
    )
    write_plan(tree)
    config_args = [LOCAL, UPSTREAM, ANCHOR_COMMIT, BRANCH_TEMPLATE]
    reconstructed_tree = reconstruct_tree(*config_args)
    reconstructed_plan = render_plan(reconstructed_tree, LOCAL, UPSTREAM)
    plan = (
        f"b0 {c1.short_str}\n"
        f"b1 {c2.short_str}\n"
        f"b2 {c3.short_str}\n"
        f"b3 {c4.short_str}"
    )
    assert reconstructed_plan == plan
    b0 = Delta([c1], None, ANCHOR_COMMIT, UPSTREAM, BRANCH_TEMPLATE)
    b1 = Delta([c2], None, ANCHOR_COMMIT, UPSTREAM, BRANCH_TEMPLATE)
    b2 = Delta([c3], None, ANCHOR_COMMIT, UPSTREAM, BRANCH_TEMPLATE)
    b3 = Delta([c4], None, ANCHOR_COMMIT, UPSTREAM, BRANCH_TEMPLATE)
    assert reconstructed_tree == {
        b0.branch_name: b0,
        b1.branch_name: b1,
        b2.branch_name: b2,
        b3.branch_name: b3,
    }


def test_plan__failed_cherry_pick(
    runner, git_repository, commit, checkout, create_branch
):
    commit(dict(a="a"), "0")
    create_branch(UPSTREAM)
    commit(dict(a="b"), "1")
    commit(dict(a="c"), "2")
    create_branch(LOCAL)
    with runner.isolated_filesystem(git_repository):
        result = runner.invoke(cli_group, ["plan", "flat"])
    assert result.exit_code == 1
    assert (
        "Error: Cherry-pick failed"
        in result.output
    )


def test_plan__duplicate_commit_names(
    runner, git_repository, commit, checkout, create_branch
):
    commit(dict(a="a"), "0")
    create_branch(UPSTREAM)
    commit(dict(a="b"), "1")
    commit(dict(a="c"), "1")
    create_branch(LOCAL)
    with runner.isolated_filesystem(git_repository):
        result = runner.invoke(cli_group, ["plan"])
    assert result.exit_code == 1
    assert (
        "Error: Duplicate commit messages found in local commits."
        in result.output
    )


def test_plan__diverged(
    runner, git_repository, commit, checkout, create_branch
):
    commit(dict(a="a"), "0")
    create_branch(LOCAL)
    commit(dict(a="b"), "1")
    create_branch(UPSTREAM)
    with runner.isolated_filesystem(git_repository):
        result = runner.invoke(cli_group, ["plan"])
    assert result.exit_code == 1
    assert "Error: Your local and upstream have diverged." in result.output


def test_plan__nonexistent_upstream(
    runner, git_repository, commit, create_branch
):
    commit(dict(a="a"), "0")
    create_branch(LOCAL)
    with runner.isolated_filesystem(git_repository):
        result = runner.invoke(cli_group, ["plan"])
    assert result.exit_code == 1
    assert f"Error: Upstream {UPSTREAM} does not exist" in result.output


def test_plan__nonexistent_local(
    runner, git_repository, commit, create_branch
):
    commit(dict(a="a"), "0")
    create_branch(UPSTREAM)
    with runner.isolated_filesystem(git_repository):
        result = runner.invoke(cli_group, ["plan"])
    assert result.exit_code == 1
    assert f"Error: Local {LOCAL} does not exist" in result.output


def test_plan__work_tree_not_clean(
    runner, git_repository, commit, create_branch
):
    commit(dict(a="a"), "0")
    create_branch(UPSTREAM)
    commit(dict(a="aa"), "1")
    create_branch(LOCAL)
    with open(git_repository / "a", "w") as f:
        f.write("ab")
    with runner.isolated_filesystem(git_repository):
        result = runner.invoke(cli_group, ["plan"])
    assert result.exit_code == 1
    assert "Error: Work tree not clean." in result.output


def test_reconstruct_tree_branch_label_first(commit, create_branch):
    commit(dict(a="a"), "0")
    create_branch(UPSTREAM)
    commit(dict(a="aa"), "1")
    commit(dict(a="ab"), "2")
    commit(dict(b="a"), "3")
    commit(dict(a="bb"), "4")
    create_branch(LOCAL)
    c1, c2, c3, c4 = get_local_commits(LOCAL, UPSTREAM)
    plan = f"""
    b {c1.sha} {c1.short_message}
    b {c2.sha} {c2.short_message}
    b1 {c3.sha} {c3.short_message}
    b2@b {c4.sha} {c4.short_message}
    """
    config_args = [LOCAL, UPSTREAM, ANCHOR_COMMIT, BRANCH_TEMPLATE]
    tree = parse_plan(plan, *config_args)
    write_plan(tree)
    reconstructed_tree = reconstruct_tree(*config_args)
    b = Delta([c1, c2], None, ANCHOR_COMMIT, UPSTREAM, BRANCH_TEMPLATE)
    b1 = Delta([c3], None, ANCHOR_COMMIT, UPSTREAM, BRANCH_TEMPLATE)
    b2 = Delta([c4], b, ANCHOR_COMMIT, UPSTREAM, BRANCH_TEMPLATE)
    assert reconstructed_tree == {
        c1.get_branch_name(BRANCH_TEMPLATE): b,
        c3.get_branch_name(BRANCH_TEMPLATE): b1,
        c4.get_branch_name(BRANCH_TEMPLATE): b2,
    }


def test_build_empty_tree(
    commit_b, upstream, commit_a, commit_c, local, git_repository
):
    config_args = [LOCAL, UPSTREAM, ANCHOR_COMMIT, BRANCH_TEMPLATE]
    tree = reconstruct_tree(*config_args)
    assert tree == {}


def test_empty_tree__git(create_branch, commit, git_repository):
    commit(dict(a="a"), "a")
    create_branch(UPSTREAM)
    commit(dict(b="b"), "b")
    create_branch(LOCAL)
    config_args = [LOCAL, UPSTREAM, ANCHOR_COMMIT, BRANCH_TEMPLATE]
    tree = reconstruct_tree(*config_args)
    assert tree == {}
