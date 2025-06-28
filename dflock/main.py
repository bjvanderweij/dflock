import configparser
import functools
import re
import subprocess
import tempfile
import typing
from dataclasses import dataclass
from graphlib import TopologicalSorter
from hashlib import md5
from pathlib import Path

import click

from dflock import utils

DEFAULT_UPSTREAM = "main"
DEFAULT_LOCAL = "main"
DEFAULT_REMOTE = "origin"
DEFAULT_BRANCH_ANCHOR = "first"  # first/last
DEFAULT_BRANCH_TEMPLATE = "{}"
DEFAULT_EDITOR = "nano"

INSTRUCTIONS = """

# Edit branch-creation plan.
#
# Commands:
# u = use commit in single-commit branch
# u@b<target-label> <commit> = use commit in single-commit branch off branch
#                              with target-label
# b<label> <commit> = use commit in labeled branch
# b<label>@b<target-label> <commit> = use commit in labeled branch off branch
#                                     with target-label
# s <commit> = do not use commit
#
# If you delete a line, the commit will not be used (equivalent to "s")
# If you remove everything, nothing will be changed
#
"""


def on_local(f):
    @functools.wraps(f)
    def wrapper(app, *args, **kwargs):
        if utils.get_current_branch() != app.local:
            raise click.ClickException(
                f"You must be on your the local branch: {app.local}"
            )
        return f(app, *args, **kwargs)

    return wrapper


def inside_work_tree(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not is_inside_work_tree():
            raise click.ClickException("No git repository detected.")
        return f(*args, **kwargs)

    return wrapper


def no_hot_branch(f) -> typing.Callable:
    @functools.wraps(f)
    def wrapper(app, *args, **kwargs):
        if utils.get_current_branch() in app.get_hot_branches():
            raise click.ClickException(
                "please switch to a branch not managed by dflock before " "continuing"
            )
        return f(app, *args, **kwargs)

    return wrapper


def undiverged(f):
    @functools.wraps(f)
    def wrapper(app, *args, **kwargs):
        if utils.have_diverged(app.upstream_name, app.local):
            click.echo(
                "Hint: Use `dfl pull` or "
                f"`git pull --rebase {app.remote} {app.upstream}` to pull "
                "upstream changes into your local branch."
            )
            raise click.ClickException("Your local and upstream have diverged.")
        return f(app, *args, **kwargs)

    return wrapper


def pass_app(f):
    @click.pass_context
    @functools.wraps(f)
    def wrapper(ctx, *args, **kwargs):
        app = App.from_config(ctx.obj["config"])
        return f(app, *args, **kwargs)

    return wrapper


def clean_work_tree(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        result = utils.run("status", "--untracked-files=no", "--porcelain")
        if bool(result.strip()):
            raise click.ClickException("Work tree not clean.")
        return f(*args, **kwargs)

    return wrapper


class DflockException(Exception):
    def __init__(self, *args, hints: None | list[str] = None, **kwargs):
        self.hints = hints
        super().__init__(*args, **kwargs)

    def emit_hints(self):
        if self.hints is not None:
            for hint in self.hints:
                click.echo(f"Hint: {hint}")


class ParsingError(DflockException):
    pass


class PlanError(DflockException):
    pass


class CherryPickFailed(DflockException):
    pass


class NoRemoteTrackingBranch(DflockException):
    pass


class Commit(typing.NamedTuple):
    sha: str
    message: str

    @classmethod
    def from_oneline(cls, oneline: str):
        """Parse from 'oneline' format of git rev-list."""
        sha, *message_words = oneline.split()
        return cls(sha, " ".join(message_words))

    @property
    def short_message(self):
        return self.message.split("\n")[0]

    @property
    def short_str(self):
        return f"{self.sha[:8]} {self.short_message}"


class Delta(typing.NamedTuple):
    commits: list[Commit]
    target: typing.Optional["Delta"]
    branch_name: str
    target_branch_name: str

    @property
    def full_branch_name(self) -> str:
        return f"refs/heads/{self.branch_name}"

    def branch_exists(self) -> bool:
        return utils.object_exists(self.full_branch_name)

    def delete_branch(self) -> None:
        utils.run("branch", "-D", self.branch_name)

    def create_branch(self) -> None:
        utils.checkout("-b", self.branch_name)

    @property
    def create_instructions(self) -> str:
        return (
            f"git checkout {self.target_branch_name}\n"
            f"git checkout -b temporary-investigation-branch\n"
            f"git cherry-pick {' '.join([c.sha for c in self.commits])}"
        )

    def cherry_pick(self) -> None:
        try:
            utils.run("cherry-pick", *[c.sha for c in self.commits])
        except subprocess.CalledProcessError:
            hint = (
                f"To reproduce the failed cherry-pick, run the following "
                f"commands:\n\n{self.create_instructions}"
            )
            raise CherryPickFailed(
                f"Cherry-pick failed at branch {self.branch_name}.", hints=[hint]
            )

    def get_force_push_command(
        self, remote: str, gitlab_merge_request: bool = False
    ) -> list[str]:
        command = [
            "push",
            "--force",
            "--set-upstream",
            remote,
            f"{self.full_branch_name}:{self.full_branch_name}",
        ]
        if gitlab_merge_request:
            command += ["--push-option", "merge_request.create"]
            if self.target is not None:
                command += [
                    "--push-option",
                    f"merge_request.target={self.target_branch_name}",
                ]
        return command

    def __str__(self) -> str:
        return "Branch {self.branch_name} with commits:" "\n".join(
            f"\t{c.short_message}" for c in self.commits
        )


class _BranchCommand(typing.NamedTuple):
    label: str
    target_label: None | str
    commit_sha: str


class _CommitList(typing.NamedTuple):
    label: str
    target_label: None | str
    commits: list[Commit]


@dataclass
class App:
    local: str
    upstream: str
    remote: str
    branch_template: str
    anchor_commit: str
    editor: str

    @classmethod
    def from_config(cls, config: typing.Mapping) -> typing.Self:
        return cls(
            local=config["local"],
            upstream=config["upstream"],
            remote=config["remote"],
            branch_template=config["branch-template"],
            anchor_commit=config["anchor-commit"],
            editor=config["editor"],
        )

    @property
    def upstream_name(self):
        if self.remote == "":
            return self.upstream
        return f"{self.remote}/{self.upstream}"

    def get_commit_branch_name(self, commit):
        uniqueish = md5(commit.message.encode()).hexdigest()[:8]
        words = re.findall(r"\w+", commit.message.lower())
        readable = "-".join(words)
        return self.branch_template.format(f"{readable}-{uniqueish}")

    def _create_delta(
        self, commits: typing.Sequence[Commit], target: None | Delta
    ) -> Delta:
        commits = list(commits)
        branch_name = (
            self.get_commit_branch_name(commits[0])
            if self.anchor_commit == "first"
            else self.get_commit_branch_name(commits[-1])
        )
        target_branch_name = (
            self.upstream_name if target is None else target.branch_name
        )
        return Delta(commits, target, branch_name, target_branch_name)

    def build_tree(self, stack: bool = True) -> dict[str, "Delta"]:
        """Create a simple plan including all local commits.

        If stack is False, treat every commit as an independent delta,
        otherwise create a stack of deltas.
        """
        commits = self._get_local_commits()
        tree: dict[str, Delta] = {}
        target = None
        for commit in commits:
            delta = self._create_delta([commit], target)
            tree[delta.branch_name] = delta
            if stack:
                target = delta
        return tree

    def reconstruct_tree(self) -> dict[str, Delta]:
        """Use local commits to reconstruct the plan.

        Assumes that the commits in local branches have the same commit messages
        as commits in local commits.

        Algorithm when branch name is derived from last commit:

        get local commits in chronological order
        get local branches
        for commit in local commits
        if branch name exists as local branch
        get n preceding commits where n is index of commit in local commits
        iterate in reverse chronological order until you encounter either
        a commit corresponding to another branch already created or an unknown
        commit.

        when name is derived from first commit:

        get local commits in chronological order
        get local branches
        for commit in local commits
        if branch name exists as local branch
        get commits in branch from tip (n_local_commits - index_of_current_commit)
            until hitting epynomous commit. Then check if previous commit is known
            as final commit of branch
            If so, set corresponding branch as target
            If not, preceding commit must be
        record the final commit in the branch
        """
        commits = self._get_local_commits()
        commits_by_message = {c.message: c for c in commits}
        local_branches = utils.get_local_branches()
        root = get_commits(self.upstream)[0]
        tree: dict[str, Delta] = {}
        for i, commit in enumerate(commits):
            if self.get_commit_branch_name(commit) in local_branches:
                if self.anchor_commit == "first":
                    delta = self._infer_delta_first_commit(
                        commit, i, commits_by_message, tree, root
                    )
                else:
                    delta = self._infer_delta_last_commit(
                        commit, i, commits_by_message, tree, root
                    )
                tree[delta.branch_name] = delta
        return tree

    def parse_plan(self, plan: str) -> dict[str, Delta]:
        tokens = _tokenize_plan(plan)
        commit_lists = self._make_commit_lists(tokens)
        return self._build_tree(commit_lists)

    def render_plan(self, tree: dict[str, Delta]) -> str:
        local_commits = self._get_local_commits()
        sorted_deltas = list(
            sorted(tree.values(), key=lambda d: local_commits.index(d.commits[0]))
        )
        lines = []
        for commit in local_commits:
            command = "s"
            delta = None
            try:
                d_i, delta = next(
                    (i, d) for i, d in enumerate(sorted_deltas) if commit in d.commits
                )
            except StopIteration:
                pass
            if delta is not None:
                command = f"b{d_i}"
                if delta.target is not None:
                    target_i = sorted_deltas.index(delta.target)
                    command += f"@b{target_i}"
            lines.append(f"{command} {commit.short_str}")
        return "\n".join(lines)

    def prune_local_branches(self, tree: dict[str, Delta]) -> None:
        hot_branches = self.get_hot_branches()
        branches_to_prune = hot_branches - set(tree.keys())
        for branch_name in branches_to_prune:
            click.echo(f"pruning {branch_name}")
            utils.run("branch", "-D", branch_name)

    def get_delta_branches(self) -> list[str]:
        branches = utils.get_local_branches()
        commits = self._get_local_commits()
        return [
            self.get_commit_branch_name(c)
            for c in commits
            if self.get_commit_branch_name(c) in branches
        ]

    def get_hot_branches(self) -> set[str]:
        commits = self._get_local_commits()
        local_branches = utils.get_local_branches()
        return set(local_branches) & set(
            self.get_commit_branch_name(c) for c in commits
        )

    def _get_local_commits(self) -> list[Commit]:
        """Return all commits between upstream and local."""
        if not utils.object_exists(self.upstream_name):
            raise click.ClickException(f"Upstream {self.upstream_name} does not exist")
        if not utils.object_exists(self.local):
            raise click.ClickException(f"Local {self.local} does not exist")
        commits = get_commits_between(self.upstream_name, self.local)
        if len(commits) != len(set(c.message for c in commits)):
            raise click.ClickException(
                "Duplicate commit messages found in local commits."
            )
        return commits

    def _infer_delta_last_commit(
        self,
        commit: Commit,
        i: int,
        commits_by_message,
        tree: dict[str, Delta],
        root: Commit,
    ) -> Delta:
        candidate_commits = get_last_n_commits(
            self.get_commit_branch_name(commit), i + 1
        )
        if self.get_commit_branch_name(
            candidate_commits[-1]
        ) != self.get_commit_branch_name(commit):
            raise click.ClickException(
                "Invalid state: dflock-managed branch name "
                f"{self.get_commit_branch_name(commit)} does not match branch "
                "name expected based on its last commit.\n\nRun\n\ngit branch "
                "-D {commit.branch_name(self.branch_template)}\n\nto remove the "
                "offending branch. Or run\n\ndfl reset\n\nif you'd like to start "
                "with a clean slate."
            )
        target = None
        commits: list[Commit] = []
        # Find the first commit of the branch by iterating through
        # preceding commits in reverse order
        for cc in reversed(candidate_commits):
            branch_name = self.get_commit_branch_name(cc)
            # When finding a commit whose branch name corresponds to
            # a branch in the tree and it isn't the current commits branch
            # name assume we've found the target branch and stop
            if branch_name in tree and (
                branch_name != self.get_commit_branch_name(commit)
            ):
                target = tree[self.get_commit_branch_name(cc)]
                break
            # if we find a commit that is in the commits by message
            elif cc.message in commits_by_message:
                commits.insert(0, commits_by_message[cc.message])
            # either we've reached the bottom of the tree, in which case
            # the preceding commits should be the same as the tip of
            # remote. If not, a commit has been renamed
            # No biggie, just print a warning
            else:
                if cc.message != root.message:
                    click.echo(
                        "warning: unknown commit message encountered: "
                        + cc.short_message
                    )
                break
        return self._create_delta(commits, target)

    def _infer_delta_first_commit(
        self,
        commit: Commit,
        i: int,
        commits_by_message: dict[str, Commit],
        tree: dict[str, Delta],
        root: Commit,
    ) -> Delta:
        n_local = len(commits_by_message)
        candidate_commits = get_last_n_commits(
            self.get_commit_branch_name(commit), n_local - i + 1
        )
        target = None
        branch_commits: list[Commit] = []
        start_index = [self.get_commit_branch_name(c) for c in candidate_commits].index(
            self.get_commit_branch_name(commit)
        )
        for delta in tree.values():
            if delta.commits[-1].message == candidate_commits[start_index - 1].message:
                target = delta
                break
        for cc in candidate_commits[start_index:]:
            if cc.message in commits_by_message:
                branch_commits.append(commits_by_message[cc.message])
            else:
                click.echo(f"warning: unknown commit message encountered: {cc.message}")
                break
        return self._create_delta(branch_commits, target)

    def _make_commit_lists(
        self,
        branch_commands: typing.Iterable[_BranchCommand],
    ) -> list[_CommitList]:
        """Build lists of contiguous commits belonging to a branch."""
        branches: list[_CommitList] = []
        local_commits = iter(self._get_local_commits())
        for bc in branch_commands:
            if len(branches) == 0 or bc.label != branches[-1].label:
                branches.append(_CommitList(bc.label, None, []))
            try:
                commit = next(
                    c for c in local_commits if c.sha.startswith(bc.commit_sha)
                )
            except StopIteration:
                raise PlanError("cannot match commits in plan to local commits")
            branches[-1].commits.append(commit)
            if bc.target_label is not None:
                if branches[-1].target_label is None:
                    branch = branches.pop(-1)
                    branches.append(branch._replace(target_label=bc.target_label))
                elif branches[-1].target_label != bc.target_label:
                    raise PlanError(
                        f"multiple targets specified for {branches[-1].label}"
                    )
        return branches

    def _build_tree(
        self,
        candidate_deltas: typing.Iterable[_CommitList],
    ) -> dict[str, Delta]:
        """Parse branching plan and return a branch DAG.

        Enforce the following constraints on the DAG:

        - branches point to either
            - the target of the last branch
            - one of the set of immediately preceding branches with the same target
        - commits in a branch appear in the same order as the local commits
        """
        deltas: dict[str, Delta] = {}
        last_target_label = None
        valid_target_labels: set[None | str] = {None}
        for d in candidate_deltas:
            if d.target_label not in valid_target_labels:
                hints = [
                    "re-order commits with "
                    f"`git rebase --interactive {self.local} {self.upstream}`"
                ]
                raise PlanError(
                    f'invalid target for "{d.label}": "{d.target_label}"', hints=hints
                )
            target_branch = None
            if d.target_label is not None:
                target_branch = deltas[d.target_label]
            if d.target_label != last_target_label:
                last_target_label = d.target_label
                valid_target_labels = {last_target_label}
            valid_target_labels.add(d.label)
            deltas[d.label] = self._create_delta(d.commits, target_branch)
        return {b.branch_name: b for b in deltas.values()}


def _tokenize_plan(plan: str) -> typing.Iterable[_BranchCommand]:
    for line in iterate_plan(plan):
        try:
            command, sha, *_ = line.split()
        except ValueError:
            raise ParsingError(
                "each line should contain at least a command and a commit SHA"
            )
        if command.startswith("b"):
            m = re.match(r"b([0-9]*)(@b?([0-9]*))?$", command)
            if not m:
                raise ParsingError(f"unrecognized command: {command}")
            label, _, target = m.groups()

            yield _BranchCommand(label, target, sha)
        elif command != "s":
            raise ParsingError(f"unrecognized command: {command}")


def is_inside_work_tree() -> bool:
    try:
        utils.run("rev-parse", "--is-inside-work-tree")
    except subprocess.CalledProcessError as cpe:
        if cpe.returncode == 128:
            return False
        raise cpe
    return True


def resolve_delta(name: str, branches: list[str]) -> str:
    name = name.strip()
    if not re.match(r"^[\w-]+$", name):
        raise ValueError(f"Invalid name: {name}")
    if m := re.match(r"^b?([0-9]+)$", name):
        index = int(m.group(1))
        if index < len(branches):
            return branches[index]
    matching_branches = [b for b in branches if name.lower() in b.lower()]
    if len(matching_branches) == 1:
        return matching_branches[0]
    raise ValueError(f"Could not match {name} to a unique branch")


def write_plan(tree: dict[str, Delta]):
    """Create feature branches based on the plan in tree.

    Start at the roots of the tree and for each branch in the topologically
    sorted branches, checkout its target (the upstream if None), delete the
    branch if it already exists, create the branch, cherry-pick its commits.

    Return a dictionary that maps each branch name to a boolean that is True
    only if the branch already existed and was re-created.
    """
    dag: dict[str, list[str]] = {}
    for name, delta in tree.items():
        if name not in dag:
            dag[name] = []
        if delta.target is not None:
            dag[name].append(delta.target.branch_name)
    ts = TopologicalSorter(dag)
    updated = {}
    for branch_name in ts.static_order():
        delta = tree[branch_name]
        utils.checkout(delta.target_branch_name)
        with utils.temporary_branch():
            try:
                delta.cherry_pick()
            except CherryPickFailed:
                try:
                    utils.run("cherry-pick", "--abort")
                except subprocess.CalledProcessError:
                    click.echo("Failed to abort cherry-pick.", err=True)
                raise
            if delta.branch_exists():
                delta.delete_branch()
                updated[branch_name] = True
            delta.create_branch()
            updated[branch_name] = False
    return updated


def iterate_plan(plan: str):
    """Iterate through lines, skipping empty lines or comments."""
    for line in plan.split("\n"):
        if line.startswith("#") or not line.strip():
            continue
        yield line


def get_remote_tracking_branch(branch) -> str:
    return utils.run(
        "for-each-ref", "--format=%(upstream:short)", f"refs/heads/{branch}"
    ).strip()


def branch_up_to_date(branch):
    remote_tracking_branch = get_remote_tracking_branch(branch)
    if remote_tracking_branch == "":
        raise NoRemoteTrackingBranch()
    return utils.run("rev-parse", remote_tracking_branch) == utils.run(
        "rev-parse", branch
    )


def get_commits_between(rev_a, rev_b) -> list[Commit]:
    """Return commits from rev_a up to and including rev_b."""
    return get_commits(f"{rev_a}..{rev_b}")


def get_commits(commits: str, number: None | int = None) -> list[Commit]:
    """Return commits chronological order."""
    args = [
        "rev-list",
        "--no-merges",
        "--format=oneline",
        commits,
    ]
    if number is not None:
        args += ["--max-count", str(number)]
    rev_list_output = utils.run(*args, "--")
    rev_list = reversed(rev_list_output.strip().split("\n"))
    return [Commit.from_oneline(line) for line in rev_list if line]


def get_last_n_commits(rev, n) -> list[Commit]:
    """Return at most n commits leading up to rev, including rev."""
    return get_commits(rev, number=n)


def edit_interactively(contents: str, editor: str) -> str:
    with tempfile.NamedTemporaryFile("w") as text_file:
        text_file.write(contents)
        text_file.seek(0)
        subprocess.run([editor, text_file.name])
        with open(text_file.name, "r") as text_file_read:
            return text_file_read.read()


def read_config(ctx, cmd, path):
    config = configparser.ConfigParser()
    config["dflock"] = {
        "upstream": DEFAULT_UPSTREAM,
        "local": DEFAULT_LOCAL,
        "remote": DEFAULT_REMOTE,
        "anchor-commit": DEFAULT_BRANCH_ANCHOR,
        "branch-template": DEFAULT_BRANCH_TEMPLATE,
        "editor": DEFAULT_EDITOR,
    }
    paths = []
    if path is not None:
        paths = [path]
    else:
        if is_inside_work_tree():
            root_path = Path(utils.run("rev-parse", "--show-toplevel").strip())
            paths = [root_path / ".dflock"]
        paths.append(Path("~/.dflock").expanduser())
    config.read(paths)
    return config


@click.group()
@click.option(
    "-c",
    "--config",
    callback=read_config,
    type=click.Path(
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        allow_dash=False,
        path_type=str,
    ),
    help="Use a custom config file.",
)
@click.pass_context
def cli_group(ctx, config):
    ctx.ensure_object(dict)
    ctx.obj["config"] = config["dflock"]


def cli():
    try:
        cli_group()
    except subprocess.CalledProcessError as exc:
        click.echo(f"Subprocess failed:\n{exc}\n", err=True)
        click.echo(f"Captured output:\n{exc.output}\n{exc.stderr}\n", err=True)
        raise


@cli_group.command
@click.argument(
    "delta-references",
    nargs=-1,
    type=str,
)
@click.option(
    "-w",
    "--write",
    is_flag=True,
    type=bool,
    help="Also detect current plan and write branches.",
)
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    type=bool,
    help="Choose which branches to push.",
)
@click.option(
    "-m",
    "--gitlab-merge-request",
    is_flag=True,
    type=bool,
    help="Use Gitlab-specific push-options to create a merge request",
)
@inside_work_tree
@pass_app
def push(app, delta_references, write, interactive, gitlab_merge_request) -> None:
    """Push deltas to the remote."""
    if app.remote == "":
        raise click.ClickException("Remote must be set.")
    tree = app.reconstruct_tree()
    if write:
        try:
            with utils.return_to_head():
                write_plan(tree)
        except CherryPickFailed as exc:
            exc.emit_hints()
            raise click.ClickException(str(exc))
    deltas = list(tree.values())
    if len(delta_references) > 0:
        branches = [d.branch_name for d in deltas]
        try:
            names = [resolve_delta(d, branches) for d in delta_references]
        except ValueError as exc:
            raise click.ClickException(str(exc))
        deltas = [tree[n] for n in names]
    for delta in deltas:
        if interactive:
            do_it = click.confirm(
                f"Push {delta.branch_name} to {app.remote}?", default=True
            )
        if not interactive or do_it:
            push_command = delta.get_force_push_command(
                app.remote, gitlab_merge_request=gitlab_merge_request
            )
            click.echo(f"Pushing {delta.branch_name}.")
            output = utils.run(*push_command)
            click.echo(output)
    click.echo("Delta branches updated.")


@cli_group.command()
@click.argument(
    "strategy",
    type=click.Choice(["detect", "stack", "flat", "empty"]),
    default="detect",
)
@click.option(
    "-e",
    "--edit",
    is_flag=True,
    type=bool,
    help="Set this flag to always edit the plan before executing it.",
)
@click.option(
    "-s",
    "--show",
    is_flag=True,
    type=bool,
    help="Only show the plan without executing it.",
)
@inside_work_tree
@pass_app
@clean_work_tree
@no_hot_branch
@undiverged
def plan(app, strategy, edit, show) -> None:
    """Create a plan and update local branches.

    The optional argument specifies the type of plan to generate. Available
    types are:

    \b
    detect (default): use the last-applied plan
    stack: package each commit in a branch and make each branch depend on the
             previous branch.
    flat: package each commit in a separate independent branch
    empty: generate an empty plan

    """
    if strategy == "stack":
        tree = app.build_tree(stack=True)
    elif strategy == "flat":
        tree = app.build_tree(stack=False)
    elif strategy == "empty":
        tree = {}
    elif strategy == "detect":
        tree = app.reconstruct_tree()
    else:
        raise ValueError("This shouldn't happen")
    plan = app.render_plan(tree)
    if (edit or strategy == "detect") and not show:
        new_plan = edit_interactively(plan + INSTRUCTIONS, app.editor)
        new_plan = "\n".join(iterate_plan(new_plan))
        if not new_plan.strip():
            click.echo("Aborting.")
            return
    else:
        new_plan = plan
    click.echo(f"{new_plan}\n")
    if not show:
        try:
            tree = app.parse_plan(new_plan)
            with utils.return_to_head():
                write_plan(tree)
            click.echo("Branches updated. Run `dfl push` to push them to a remote.")
            app.prune_local_branches(tree)
        except ParsingError as exc:
            raise click.ClickException(str(exc))
        except (PlanError, CherryPickFailed) as exc:
            exc.emit_hints()
            raise click.ClickException(str(exc))


@cli_group.command()
@click.option(
    "-t",
    "--show-targets",
    is_flag=True,
    type=bool,
    help="Print target of each branch",
)
@inside_work_tree
@pass_app
def status(app, show_targets) -> None:
    """Show status of delta branches."""
    if not utils.object_exists(app.upstream):
        raise click.ClickException(f"Upstream {app.upstream} does not exist")
    if not utils.object_exists(app.local):
        raise click.ClickException(f"Local {app.local} does not exist")
    diverged = utils.have_diverged(app.upstream_name, app.local)
    branches = app.get_delta_branches()
    on_local = utils.get_current_branch() == app.local
    if on_local:
        click.echo("On local branch.")
    else:
        click.echo("NOT on local branch.")
    if diverged:
        click.echo("Local and upstream have diverged")
    if len(branches) > 0:
        if show_targets:
            tree = app.reconstruct_tree()
        click.echo("\nDeltas:")
        for i, branch in enumerate(branches):
            try:
                up_to_date = branch_up_to_date(branch)
                click.echo(
                    f"{'b' + str(i):>4}: "
                    f"{branch}{'' if up_to_date else ' (diverged)'}"
                )
            except NoRemoteTrackingBranch:
                click.echo(f"{'b' + str(i):>4}: {branch} (not pushed)")
            if show_targets:
                target = tree[branch].target_branch_name
                click.echo(f"{' ' * 6}@ {target}")


@cli_group.command()
@inside_work_tree
@clean_work_tree
@pass_app
@undiverged
@on_local
def remix(app) -> None:
    """Alias for `git rebase -i <upstream>`.

    Only works when on local.
    """
    subprocess.run(f"git rebase -i {app.upstream_name}", shell=True)


@cli_group.command()
@inside_work_tree
@pass_app
@on_local
def pull(app) -> None:
    """Alias for `git pull --rebase <upstream>`.

    Only works when on local.
    """
    if app.remote == "":
        raise click.ClickException("Remote must be set.")
    subprocess.run(f"git pull --rebase {app.remote} {app.upstream}", shell=True)


@cli_group.command()
@inside_work_tree
@pass_app
@undiverged
def log(app) -> None:
    """Alias for `git log <local> ^<upstream>`."""
    if utils.get_current_branch() != app.local:
        click.echo("Warning: not on local branch.")
    subprocess.run(f"git log {app.local} ^{app.upstream_name}", shell=True)


@cli_group.command()
@inside_work_tree
@click.argument("delta-reference", type=str)
@pass_app
def checkout(app, delta_reference) -> None:
    """Checkout deltas or the local branch.

    If DELTA_REFERENCE is "local" or the name of your local branch, checkout
    your local branch.

    If DELTA_REFERENCE is a number (optionally prefixed by 'b'), go to the
    delta with that index.

    Otherwise, try to do a partial match against your delta branch names.
    This only works if there is a unique match."""
    if delta_reference in ["local", app.local]:
        branch = app.local
    else:
        branches = app.get_delta_branches()
        try:
            branch = resolve_delta(delta_reference, branches)
        except ValueError as exc:
            raise click.ClickException(str(exc))
    subprocess.run(f"git checkout {branch}", shell=True)


@cli_group.command()
@inside_work_tree
@clean_work_tree
@pass_app
@no_hot_branch
@undiverged
def write(app) -> None:
    """Update deltas based on the current plan."""
    tree = app.reconstruct_tree()
    try:
        with utils.return_to_head():
            write_plan(tree)
    except CherryPickFailed as exc:
        exc.emit_hints()
        raise click.ClickException(str(exc))
    click.echo("Delta branches updated.")


@cli_group.command()
@click.option("-y", "--yes", is_flag=True, help="Do not ask for confirmation.")
@click.pass_context
@inside_work_tree
def reset(app, yes) -> None:
    """Reset the plan.

    This removes all dflock-managed branches.
    """
    branches = app.get_delta_branches()
    if len(branches) == 0:
        click.echo("No active branches found")
        return
    if not yes:
        click.echo("This will delete the following branches:")
        for branch_name in branches:
            click.echo(branch_name)
        confirmed = click.confirm("Continue?")
    if confirmed or yes:
        for branch_name in branches:
            utils.run("branch", "-D", branch_name)
