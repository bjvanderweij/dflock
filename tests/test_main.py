from functools import partial
from pathlib import Path
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

from dflock import utils
from dflock.main import (
    App,
    CherryPickFailed,
    Commit,
    GitStateError,
    ParsingError,
    PlanError,
    cli_group,
    read_config,
    write_plan,
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

COMMANDS = [
    "checkout",
    "log",
    "plan",
    "pull",
    "push",
    "remix",
    "reset",
    "status",
    "write",
]


@pytest.fixture(autouse=True)
def configuration(tmp_path):
    test_config_path = tmp_path / ".dflock"

    def new_read_config(ctx, cmd, path):
        return read_config(ctx, cmd, test_config_path)

    with open(test_config_path, "w") as f:
        f.write(TEST_CONFIG)
    with patch("dflock.main.read_config", new_read_config) as mock:
        yield mock


@pytest.fixture()
def git_repository(tmp_path):
    new_run = partial(utils.run, cwd=tmp_path)
    with patch("dflock.utils.run", new_run):
        utils.run("init")
        utils.run("config", "user.email", "you@example.com")
        utils.run("config", "user.name", "Your Name")
        yield Path(tmp_path)


@pytest.fixture()
def runner(git_repository):
    runner = CliRunner()
    with runner.isolated_filesystem(git_repository):
        yield runner


@pytest.fixture()
def upstream(git_repository):
    utils.run(*(f"checkout -b {UPSTREAM}".split()), cwd=git_repository)
    utils.run(*("checkout -".split()), cwd=git_repository)


@pytest.fixture()
def local(git_repository):
    utils.run(*(f"checkout -b {LOCAL}".split()), cwd=git_repository)
    utils.run(*("checkout -".split()), cwd=git_repository)


@pytest.fixture()
def app(configuration):
    return App.from_config(configuration(None, None, None))


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
    commits = [Commit("0", "a"), Commit("1", "b"), Commit("2", "c"), Commit("3", "d")]

    def branch_must_be_none(branch=None):
        assert (
            branch is None
        ), "this patch should not be used for _get_branch_commits with an argument"
        return commits

    with patch(
        "dflock.main.App._get_branch_commits",
        side_effect=branch_must_be_none,
    ):
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
    def _create_branch(name, checkout=False):
        utils.run("checkout", "-b", name, cwd=git_repository)
        if not checkout:
            utils.run("checkout", "-", cwd=git_repository)

    return _create_branch


@pytest.fixture
def checkout(git_repository):
    def _checkout(name):
        utils.run("checkout", name, cwd=git_repository)

    return _checkout


@pytest.fixture(params=["first", "last"])
def anchor_commit(app, request):
    app.anchor_commit = request.param
    return app.anchor_commit


def test_parse_plan__syntax_errors(app, local_commits):
    with pytest.raises(ParsingError):
        app.parse_plan("s 0 a\na 1 b\ns 2 v") == {}
    with pytest.raises(ParsingError):
        app.parse_plan("d@s 0 a") == {}
    with pytest.raises(ParsingError):
        app.parse_plan("s 0 a\nb\ns 2 v") == {}


def test_parse_plan__illegal_plans(app, local_commits):
    with pytest.raises(PlanError, match="cannot match"):
        # Unrecognized commit
        app.parse_plan("s 0 a\nd1 a\ns 2 v") == {}
    with pytest.raises(PlanError, match="cannot match"):
        # Out of order commits
        app.parse_plan("d 1 a\nd 0 foo") == {}
    with pytest.raises(PlanError, match="invalid target"):
        # Non contiguous commits in branch
        app.parse_plan("d 0 a\nd1@ 1 foo\nd  2 v") == {}
    with pytest.raises(PlanError, match="invalid target"):
        # Incorrect target
        app.parse_plan("d@1 0 a\nd1 1 foo") == {}
    with pytest.raises(PlanError, match="multiple targets"):
        # Conflicting targets
        app.parse_plan("d 0 a\nd1 1\nd2@ 2 v\nd2@1 3") == {}
    with pytest.raises(PlanError, match="invalid target"):
        # "Crossing" branches
        app.parse_plan("d 0 a\nd1@ 1 foo\nd2 2 v") == {}


def test_parse_plan__legal_plans(app, local_commits, anchor_commit):
    a, b, c, d = local_commits
    # Equivalent plans
    delta = app._create_delta([c], None)
    tree = {delta.branch_name: delta}
    v0 = app.parse_plan("s 0 a\ns 1 b\nd0 2 v")
    v1 = app.parse_plan("s 0 a\nd0 2 v")
    v2 = app.parse_plan("d0 2 v")
    v3 = app.parse_plan("d 2 v")
    v4 = app.parse_plan("d 2")
    assert v0 == v1 == v2 == v3 == v4 == tree
    # Empty plans
    assert app.parse_plan("") == {}
    assert app.parse_plan("s 0 a\ns 1 b\ns 2 v") == {}
    # Optional target specifications
    d0 = app._create_delta([a], None)
    d1 = app._create_delta([b, c], d0)
    tree = {d.branch_name: d for d in [d0, d1]}
    variant_1 = app.parse_plan("d 0 a\nd1@ 1 b\nd1 2 v")
    variant_2 = app.parse_plan("d 0 a\nd1 1 b\nd1@ 2 v")
    variant_3 = app.parse_plan("d 0 a\nd1@ 1 b\nd1@ 2 v")
    variant_4 = app.parse_plan("d 0 a\nd1@ 1 b\nd1@ 2 v")
    assert tree == variant_1 == variant_2 == variant_3 == variant_4
    d0 = app._create_delta([a, c], None)
    tree = {d0.branch_name: d0}
    assert app.parse_plan("d 0 a\ns 1 foo\nd 2 v") == tree
    d0 = app._create_delta([a], None)
    d1 = app._create_delta([b], d0)
    d2 = app._create_delta([c], d1)
    tree = {d.branch_name: d for d in [d0, d1, d2]}
    variant_1 = app.parse_plan("d0 0 a\nd1@0 1 foo\nd2@1 2 v")
    variant_2 = app.parse_plan("d 0 a\nd1@ 1 foo\nd2@1 2 v")
    assert tree == variant_1
    assert tree == variant_2


@pytest.fixture
def independent_commits(app, commit, create_branch):
    commit(dict(x="x"), "0")
    create_branch(UPSTREAM)
    commit(dict(a="a"), "1")
    commit(dict(b="b"), "2")
    commit(dict(c="c"), "3")
    commit(dict(d="d"), "4")
    create_branch(LOCAL)
    return app._get_branch_commits()


@pytest.fixture
def serially_dependent_commits(app, commit, create_branch):
    commit(dict(a="a"), "0")
    create_branch(UPSTREAM)
    commit(dict(a="b"), "1")
    commit(dict(a="c"), "2")
    commit(dict(a="d"), "3")
    commit(dict(a="e"), "4")
    create_branch(LOCAL)
    return app._get_branch_commits()


@pytest.fixture
def dag_commits(app, commit, create_branch):
    commit(dict(a="a"), "0")
    create_branch(UPSTREAM)
    commit(dict(a="b"), "1")
    commit(dict(a="c"), "2")
    commit(dict(b="a"), "3")
    commit(dict(a="d"), "4")
    create_branch(LOCAL)
    return app._get_branch_commits()


def test_reconstruct_tree__unrecognized_commit(
    app, anchor_commit, checkout, commit, capsys, dag_commits
):
    c1, c2, c3, c4 = dag_commits
    plan = f"d0 {c1.short_str}\n" f"d0 {c2.short_str}\n"
    tree = app.parse_plan(plan)
    write_plan(tree)
    branches = list(tree.keys())
    checkout(branches[0])
    # Commit to an ephemeral branch
    message = "unfamiliar message"
    commit(dict(a="d"), "unfamiliar message")
    app.reconstruct_tree()
    captured = capsys.readouterr()
    assert (
        f"WARNING: Unfamiliar commit message encountered on {branches[0]}: {message}."
        in captured.err
    )
    if anchor_commit == "last":
        assert (
            f"WARNING: Branch name of inferred delta {branches[0]} is inconsistent with last commit."
            in captured.err
        )


def test_reconstruct_tree__missing_commits(
    app, checkout, git_repository, capsys, dag_commits
):
    c1, c2, c3, c4 = dag_commits
    plan = f"d0 {c1.short_str}\n" f"d0 {c2.short_str}\n"
    app.anchor_commit = "last"
    tree = app.parse_plan(plan)
    write_plan(tree)
    branches = list(tree.keys())
    checkout(branches[0])
    # Remove last two commits
    utils.run("reset", "HEAD~1", cwd=git_repository)
    app.reconstruct_tree()
    captured = capsys.readouterr()
    assert (
        f"WARNING: Branch name of inferred delta {branches[0]} is inconsistent with last commit."
        == captured.err.strip()
    )


def test_reconstruct_tree__missing_all(
    app, anchor_commit, checkout, git_repository, capsys, dag_commits
):
    c1, c2, c3, c4 = dag_commits
    plan = f"d0 {c1.short_str}\n" f"d0 {c2.short_str}\n"
    tree = app.parse_plan(plan)
    write_plan(tree)
    branches = list(tree.keys())
    checkout(branches[0])
    # Remove last two commits
    utils.run("reset", "HEAD~2", cwd=git_repository)
    with pytest.raises(GitStateError) as exc_info:
        app.reconstruct_tree()
    assert f"Ephemeral branch {branches[0]} has no commits." == str(exc_info.value)


def test_reconstruct_tree__missing_one(
    app, anchor_commit, checkout, git_repository, capsys, dag_commits
):
    c1, c2, c3, c4 = dag_commits
    plan = f"d0 {c1.short_str}\n" f"d1@0 {c2.short_str}\n"
    tree = app.parse_plan(plan)
    write_plan(tree)
    branches = list(tree.keys())
    checkout(branches[1])
    # Remove last two commits
    utils.run("reset", "HEAD~1", cwd=git_repository)
    with pytest.raises(GitStateError) as exc_info:
        app.reconstruct_tree()
    assert f"No local commits on delta {branches[-1]}." == str(exc_info.value)


def test_reconstruct_tree__anchor_commit(app, capsys, anchor_commit, dag_commits):
    c1, c2, c3, c4 = dag_commits
    plan = (
        f"d0 {c1.short_str}\n"
        f"d0 {c2.short_str}\n"
        f"d1 {c3.short_str}\n"
        f"d2@0 {c4.short_str}"
    )
    tree = app.parse_plan(plan)
    write_plan(tree)
    reconstructed_tree = app.reconstruct_tree()
    d = app._create_delta([c1, c2], None)
    d1 = app._create_delta([c3], None)
    d2 = app._create_delta([c4], d)
    if anchor_commit == "first":
        assert reconstructed_tree == {
            app.get_commit_branch_name(c1): d,
            app.get_commit_branch_name(c3): d1,
            app.get_commit_branch_name(c4): d2,
        }
    else:
        assert reconstructed_tree == {
            app.get_commit_branch_name(c2): d,
            app.get_commit_branch_name(c3): d1,
            app.get_commit_branch_name(c4): d2,
        }
    captured = capsys.readouterr()
    assert "WARNING: " not in captured.err


def test_reconstruct_tree(app, capsys, dag_commits, anchor_commit):
    c1, c2, c3, c4 = dag_commits
    plan = (
        f"d0 {c1.short_str}\n"
        f"d0 {c2.short_str}\n"
        f"d1 {c3.short_str}\n"
        f"d2@0 {c4.short_str}"
    )
    tree = app.parse_plan(plan)
    write_plan(tree)
    reconstructed_tree = app.reconstruct_tree()
    reconstructed_plan = app.render_plan(reconstructed_tree)
    assert reconstructed_plan == plan
    d0 = app._create_delta([c1, c2], None)
    d1 = app._create_delta([c3], None)
    d2 = app._create_delta([c4], d0)
    assert reconstructed_tree == {
        d0.branch_name: d0,
        d1.branch_name: d1,
        d2.branch_name: d2,
    }
    captured = capsys.readouterr()
    assert "WARNING: " not in captured.err


def test_reconstruct_tree_stacked(
    app, capsys, serially_dependent_commits, anchor_commit
):
    c1, c2, c3, c4 = serially_dependent_commits
    tree = app.build_tree(stack=True)
    write_plan(tree)
    reconstructed_tree = app.reconstruct_tree()
    reconstructed_plan = app.render_plan(reconstructed_tree)
    plan = (
        f"d0 {c1.short_str}\n"
        f"d1@0 {c2.short_str}\n"
        f"d2@1 {c3.short_str}\n"
        f"d3@2 {c4.short_str}"
    )
    assert reconstructed_plan == plan
    d0 = app._create_delta([c1], None)
    d1 = app._create_delta([c2], d0)
    d2 = app._create_delta([c3], d1)
    d3 = app._create_delta([c4], d2)
    assert reconstructed_tree == {
        d0.branch_name: d0,
        d1.branch_name: d1,
        d2.branch_name: d2,
        d3.branch_name: d3,
    }
    captured = capsys.readouterr()
    assert "WARNING: " not in captured.err


@pytest.mark.parametrize("cmd", COMMANDS)
def test_plan__not_a_git_repo(cmd):
    runner = CliRunner()
    with runner.isolated_filesystem():
        if cmd == "checkout":
            result = runner.invoke(cli_group, [cmd, "local"])
        else:
            result = runner.invoke(cli_group, [cmd])
    assert result.exit_code == 1
    assert "No git repository detected." in result.output


def test_reconstruct_tree_independent(app, independent_commits, anchor_commit):
    c1, c2, c3, c4 = independent_commits
    tree = app.build_tree(stack=False)
    write_plan(tree)
    reconstructed_tree = app.reconstruct_tree()
    reconstructed_plan = app.render_plan(reconstructed_tree)
    plan = (
        f"d0 {c1.short_str}\n"
        f"d1 {c2.short_str}\n"
        f"d2 {c3.short_str}\n"
        f"d3 {c4.short_str}"
    )
    assert reconstructed_plan == plan
    d0 = app._create_delta([c1], None)
    d1 = app._create_delta([c2], None)
    d2 = app._create_delta([c3], None)
    d3 = app._create_delta([c4], None)
    assert reconstructed_tree == {
        d0.branch_name: d0,
        d1.branch_name: d1,
        d2.branch_name: d2,
        d3.branch_name: d3,
    }


def test_plan__failed_cherry_pick(
    runner, git_repository, commit, checkout, create_branch
):
    commit(dict(a="a"), "0")
    create_branch(UPSTREAM)
    commit(dict(a="b"), "1")
    commit(dict(a="c"), "2")
    create_branch(LOCAL)
    result = runner.invoke(cli_group, ["plan", "flat"])
    assert result.exit_code == 1
    assert "Error: Cherry-pick failed" in result.output


def test_plan__duplicate_commit_names(
    runner, git_repository, commit, checkout, create_branch
):
    commit(dict(a="a"), "0")
    create_branch(UPSTREAM)
    commit(dict(a="b"), "1")
    commit(dict(a="c"), "1")
    create_branch(LOCAL)
    result = runner.invoke(cli_group, ["plan"])
    assert result.exit_code == 1
    assert "Duplicate commit messages found in local commits." in result.output


def test_plan__diverged(runner, git_repository, commit, checkout, create_branch):
    commit(dict(a="a"), "0")
    create_branch(LOCAL)
    commit(dict(a="b"), "1")
    create_branch(UPSTREAM)
    result = runner.invoke(cli_group, ["plan"])
    assert result.exit_code == 1
    assert "Error: Your local and upstream have diverged." in result.output


def test_plan__nonexistent_upstream(runner, git_repository, commit, create_branch):
    commit(dict(a="a"), "0")
    create_branch(LOCAL)
    result = runner.invoke(cli_group, ["plan"])
    assert result.exit_code == 1
    assert f"Upstream {UPSTREAM} does not exist" in result.output


def test_plan__nonexistent_local(runner, git_repository, commit, create_branch):
    commit(dict(a="a"), "0")
    create_branch(UPSTREAM)
    result = runner.invoke(cli_group, ["plan"])
    assert result.exit_code == 1
    assert f"Local {LOCAL} does not exist" in result.output


def test_plan__work_tree_not_clean(runner, git_repository, commit, create_branch):
    commit(dict(a="a"), "0")
    create_branch(UPSTREAM)
    commit(dict(a="aa"), "1")
    create_branch(LOCAL)
    with open(git_repository / "a", "w") as f:
        f.write("ab")
    result = runner.invoke(cli_group, ["plan"])
    assert result.exit_code == 1
    assert "Work tree not clean." in result.output


def test_reconstruct_tree_branch_label_first(app, commit, create_branch):
    commit(dict(a="a"), "0")
    create_branch(UPSTREAM)
    commit(dict(a="aa"), "1")
    commit(dict(a="ab"), "2")
    commit(dict(b="a"), "3")
    commit(dict(a="bb"), "4")
    create_branch(LOCAL)
    c1, c2, c3, c4 = app._get_branch_commits()
    plan = f"""
    d {c1.sha} {c1.short_message}
    d {c2.sha} {c2.short_message}
    d1 {c3.sha} {c3.short_message}
    d2@ {c4.sha} {c4.short_message}
    """
    tree = app.parse_plan(plan)
    write_plan(tree)
    reconstructed_tree = app.reconstruct_tree()
    d = app._create_delta([c1, c2], None)
    d1 = app._create_delta([c3], None)
    d2 = app._create_delta([c4], d)
    assert reconstructed_tree == {
        app.get_commit_branch_name(c1): d,
        app.get_commit_branch_name(c3): d1,
        app.get_commit_branch_name(c4): d2,
    }


def test_build_empty_tree(
    app, commit_b, upstream, commit_a, commit_c, local, git_repository
):
    tree = app.reconstruct_tree()
    assert tree == {}


def test_empty_tree__git(app, create_branch, commit, git_repository):
    commit(dict(a="a"), "a")
    create_branch(UPSTREAM)
    commit(dict(b="b"), "b")
    create_branch(LOCAL)
    tree = app.reconstruct_tree()
    assert tree == {}


def test_status__on_local(runner, commit, create_branch, git_repository):
    commit(dict(a="a"), "a")
    create_branch(UPSTREAM)
    commit(dict(b="b"), "b")
    create_branch(LOCAL, checkout=True)
    result = runner.invoke(cli_group, ["status"])
    assert result.exit_code == 0
    assert "You are on the local branch." in result.output


def test_status__on_ephemeral(
    runner, commit, app, checkout, create_branch, git_repository
):
    commit(dict(a="a"), "a")
    create_branch(UPSTREAM)
    sha = commit(dict(b="b"), "b")
    c0 = Commit(sha, "b")
    branch_name = app.get_commit_branch_name(c0)
    create_branch(branch_name)
    create_branch(LOCAL)
    checkout(branch_name)
    result = runner.invoke(cli_group, ["status"])
    assert result.exit_code == 0
    assert "You are on an ephemeral branch." in result.output


def test_status__not_on_local(runner, commit, create_branch, git_repository):
    commit(dict(a="a"), "a")
    create_branch(UPSTREAM)
    commit(dict(b="b"), "b")
    create_branch(LOCAL)
    result = runner.invoke(cli_group, ["status"])
    assert result.exit_code == 0
    assert "You are not on a branch known to dflock." in result.output


def test_status__show_branches(app, runner, commit, create_branch, git_repository):
    commit(dict(a="a"), "a")
    create_branch(UPSTREAM)
    sha = commit(dict(b="b"), "b")
    c0 = Commit(sha, "b")
    branch_name = app.get_commit_branch_name(c0)
    create_branch(branch_name)
    create_branch(LOCAL)
    result = runner.invoke(cli_group, ["status"])
    assert result.exit_code == 0
    assert "Deltas:" in result.output
    assert branch_name in result.output


def test_status__show_branches_with_targets(
    app, runner, commit, create_branch, git_repository
):
    commit(dict(a="a"), "a")
    create_branch(UPSTREAM)
    sha = commit(dict(b="b"), "b")
    c0 = Commit(sha, "b")
    branch_name = app.get_commit_branch_name(c0)
    create_branch(branch_name)
    create_branch(LOCAL)
    result = runner.invoke(cli_group, ["status", "--show-targets"])
    assert result.exit_code == 0
    assert "Deltas:" in result.output
    assert branch_name in result.output
