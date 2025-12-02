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

# Edit the integration plan.
#
# Commands:
# d<label> <commit> = use commit in labeled delta
# d<label>@d<target-label> <commit> = use commit in labeled delta depending on
#                                     delta with target-label
# s <commit> = do not use commit
#
# If you delete a line, the commit will not be used (equivalent to "s")
# If you remove everything, the plan creation is aborted.
#
"""


def local_and_upstream_exist(f):
    @functools.wraps(f)
    def wrapper(app, *args, **kwargs):
        if not utils.object_exists(app.local):
            hints = ['use "dflock init" to configure dflock.']
            raise GitStateError(f"Local {app.local} does not exist.", hints=hints)
        if not utils.object_exists(app.upstream_name):
            hints = ['use "dflock init" to configure dflock.']
            raise GitStateError(
                f"Upstream {app.upstream_name} does not exist.", hints=hints
            )
        return f(app, *args, **kwargs)

    return wrapper


def on_local(f):
    @functools.wraps(f)
    @local_and_upstream_exist
    def wrapper(app, *args, **kwargs):
        if utils.get_current_branch() != app.local:
            hints = ['use "dfl checkout" to return to local.']
            raise GitStateError(
                f"you must be on the local branch: {app.local}.", hints=hints
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
            raise DflockException(
                "You're on an ephemeral branch. Switch to another branch before continuing.",
                hints=['you can use "dfl checkout" to check out the local branch.'],
            )
        return f(app, *args, **kwargs)

    return wrapper


def valid_local_commits(f):
    @functools.wraps(f)
    @local_and_upstream_exist
    def wrapper(app, *args, **kwargs):
        commits = app._get_branch_commits()
        if len(commits) != len(set(c.message for c in commits)):
            hints = ['use "dfl remix" to edit local commit messages.']
            raise GitStateError(
                "Duplicate commit messages found in local commits.", hints=hints
            )
        return f(app, *args, **kwargs)

    return wrapper


def remote_required(f):
    @functools.wraps(f)
    def wrapper(app, *args, **kwargs):
        if app.remote == "":
            hint = 'use "dflock init" to generate a configuration file interactively'
            raise DflockException("No remote configured.", hints=[hint])
        return f(app, *args, **kwargs)

    return wrapper


def undiverged(f):
    @functools.wraps(f)
    def wrapper(app, *args, **kwargs):
        if utils.have_diverged(app.upstream_name, app.local):
            hints = ['use "dfl pull" to pull upstream changes into local.']
            raise GitStateError("Your local and upstream have diverged.", hints=hints)
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
            hints = ['use "git stash" to stash uncommitted changes.']
            raise GitStateError("Work tree not clean.", hints=hints)
        return f(*args, **kwargs)

    return wrapper


class DflockException(Exception):
    def __init__(self, *args, hints: None | list[str] = None, **kwargs):
        self.hints = [] if hints is None else hints
        super().__init__(*args, **kwargs)

    def handle_in_cli(self):
        msg = str(self)
        if len(self.hints) > 0:
            msg += "\n" + "\n".join(f"Hint: {h}" for h in self.hints)
        raise click.ClickException(msg)


class ParsingError(DflockException):
    pass


class PlanError(DflockException):
    pass


class CherryPickFailed(DflockException):
    pass


class NoRemoteTrackingBranch(DflockException):
    pass


class GitStateError(DflockException):
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
    def short_message(self) -> str:
        return self.message.split("\n")[0]

    @property
    def short_str(self) -> str:
        return f"{self.sha[:8]} {self.short_message}"


class Delta(typing.NamedTuple):
    commits: tuple[Commit, ...]
    target: typing.Optional["Delta"]
    branch_name: str
    target_branch: str
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
                f"commands:\n\n{self.create_instructions}\n\n"
                "After running these commands you can return to your local branch "
                "by running:\n\n"
                "git cherry-pick --abort\n"
                "dfl checkout"
            )
            raise CherryPickFailed(
                f"Cherry-pick failed at branch {self.branch_name}.", hints=[hint]
            )

    def get_force_push_command(
        self, remote: str, merge_request: bool = False, without_lease: bool = False
    ) -> list[str]:
        if without_lease:
            force_option = "--force"
        else:
            force_option = "--force-with-lease"
        command = [
            "push",
            "--set-upstream",
            force_option,
            remote,
            f"{self.full_branch_name}:{self.full_branch_name}",
        ]
        if not without_lease:
            command.append("--force-with-lease")
        if merge_request:
            command += ["--push-option", "merge_request.create"]
            if self.target is not None:
                command += [
                    "--push-option",
                    f"merge_request.target={self.target_branch_name}",
                ]
        return command

    def __str__(self) -> str:
        return f"Branch {self.branch_name} with commits:\n" + "\n".join(
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
    change_request_templates: dict[str, str]

    @classmethod
    def from_config(cls, config: typing.Mapping) -> "App":
        dflock = config["dflock"]
        integrations = [
            (k, k.split(".")[1])
            for k in config.keys()
            if re.match(r"^integrations.[a-z-]+$", k)
        ]
        change_request_templates = {}
        for config_key, integration in integrations:
            change_request_templates[integration] = config[config_key][
                "change-request-template"
            ]
        return cls(
            local=dflock["local"],
            upstream=dflock["upstream"],
            remote=dflock["remote"],
            branch_template=dflock["branch-template"],
            anchor_commit=dflock["anchor-commit"],
            editor=dflock["editor"],
            change_request_templates=change_request_templates,
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

    def build_tree(self, stack: bool = True) -> dict[str, "Delta"]:
        """Create a simple plan including all local commits.

        If stack is False, treat every commit as an independent delta,
        otherwise create a stack of deltas.
        """
        commits = self._get_branch_commits()
        tree: dict[str, Delta] = {}
        target = None
        for commit in commits:
            delta = self._create_delta([commit], target)
            tree[delta.branch_name] = delta
            if stack:
                target = delta
        return tree

    def validate_ephemeral_branch(self, branch_name, commits, delta_commits):
        unrecognized = set(c.message for c in commits) - set(
            c.message for c in delta_commits
        )
        if len(unrecognized) > 0:
            for message in unrecognized:
                click.echo(
                    f"WARNING: Unfamiliar commit message encountered on {branch_name}: {message}.",
                    err=True,
                )
        if self.anchor_commit == "first":
            anchor_commit_branch_name = self.get_commit_branch_name(commits[0])
        else:
            anchor_commit_branch_name = self.get_commit_branch_name(commits[-1])
        if branch_name != anchor_commit_branch_name:
            click.echo(
                f"WARNING: Branch name of inferred delta {branch_name} is inconsistent with {self.anchor_commit} commit.",
                err=True,
            )

    def reconstruct_tree(self) -> dict[str, Delta]:
        local_commits = self._get_branch_commits()
        local_branches = utils.get_local_branches()
        branch_names_by_last_commit: dict[str, str] = {}
        deltas: dict[str, Delta] = {}
        for commit in local_commits:
            branch_name = self.get_commit_branch_name(commit)
            if branch_name in local_branches:
                commits = self._get_branch_commits(branch_name)
                if len(commits) == 0:
                    raise GitStateError(
                        f"Ephemeral branch {branch_name} has no commits."
                    )
                messages = [c.message for c in commits]
                target: Delta | None = None
                delta_start = 0
                for i, msg in enumerate(reversed(messages)):
                    if msg in branch_names_by_last_commit:
                        target = deltas[branch_names_by_last_commit[msg]]
                        delta_start = len(messages) - i
                        break
                branch_names_by_last_commit[commits[-1].message] = branch_name
                delta_commits = [
                    c for c in local_commits if c.message in messages[delta_start:]
                ]
                if len(delta_commits) == 0:
                    raise GitStateError(f"No local commits on delta {branch_name}.")
                self.validate_ephemeral_branch(
                    branch_name, commits[delta_start:], delta_commits
                )
                deltas[branch_name] = self._create_delta(delta_commits, target)
        return deltas

    def parse_plan(self, plan: str) -> dict[str, Delta]:
        tokens = _tokenize_plan(plan)
        commit_lists = self._make_commit_lists(tokens)
        return self._build_tree(commit_lists)

    def render_plan(self, tree: dict[str, Delta], include_skipped=True) -> str:
        local_commits = self._get_branch_commits()
        sorted_deltas = sorted(
            tree.values(), key=lambda d: local_commits.index(d.commits[0])
        )
        delta_indices = {d: i for i, d in enumerate(sorted_deltas)}
        lines = []
        for commit in local_commits:
            command = "s"
            for delta, index in delta_indices.items():
                if commit in delta.commits:
                    command = f"d{index}"
                    if delta.target is not None:
                        command += f"@{delta_indices[delta.target]}"
                    lines.append(f"{command} {commit.short_str}")
                    break
            else:
                if include_skipped:
                    lines.append(f"s {commit.short_str}")
        return "\n".join(lines)

    def prune_local_branches(
        self, tree: None | dict[str, Delta] = None, hot_branches=None
    ) -> None:
        if tree is None:
            tree = self.reconstruct_tree()
        if hot_branches is None:
            hot_branches = self.get_hot_branches()
        branches_to_prune = hot_branches - set(tree.keys())
        for branch_name in branches_to_prune:
            click.echo(f"Pruning {branch_name}.")
            utils.run("branch", "-D", branch_name)

    def create_change_request_command(
        self, integration: str, source_branch: str, target_branch: str
    ) -> str:
        return self.change_request_templates[integration].format(
            source=source_branch, target=target_branch
        )

    def get_delta_branches(self) -> list[str]:
        branches = utils.get_local_branches()
        commits = self._get_branch_commits()
        return [
            self.get_commit_branch_name(c)
            for c in commits
            if self.get_commit_branch_name(c) in branches
        ]

    def get_hot_branches(self) -> set[str]:
        commits = self._get_branch_commits()
        local_branches = utils.get_local_branches()
        return set(local_branches) & set(
            self.get_commit_branch_name(c) for c in commits
        )

    def print_deltas(
        self, deltas: dict[str, None | str], highlight: None | str = None
    ) -> None:
        for i, (branch, target) in enumerate(deltas.items()):
            status = ""
            try:
                up_to_date = branch_up_to_date(branch)
                if not up_to_date:
                    status = " (diverged)"
            except NoRemoteTrackingBranch:
                status = " (not pushed)"
            line = f"{'d' + str(i):>4}: {branch}{status}"
            if highlight == branch:
                click.echo("\033[92m" + line + "\033[0m")
            else:
                click.echo(line)
            if target is not None:
                click.echo(f"{' ' * 6}@ {target}")

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
        target_branch = self.upstream if target is None else target.branch_name
        return Delta(
            tuple(commits), target, branch_name, target_branch, target_branch_name
        )

    def _get_branch_commits(self, branch: None | str = None) -> list[Commit]:
        """Return all commits between upstream and branch.

        If branch is None, the local branch is used.
        """
        if branch is None:
            branch = self.local
        commits = get_commits_between(self.upstream_name, branch)
        return commits

    def _make_commit_lists(
        self,
        branch_commands: typing.Iterable[_BranchCommand],
    ) -> list[_CommitList]:
        """Build lists of contiguous commits belonging to a branch."""
        branches: list[_CommitList] = []
        local_commits = iter(self._get_branch_commits())
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
                hints = ['re-order commits with "dfl remix".']
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
        if command.startswith("d"):
            m = re.match(r"d([0-9]*)(@d?([0-9]*))?$", command)
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


@clean_work_tree
def write_plan(tree: dict[str, Delta]) -> None:
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
                    click.echo("WARNING: Failed to abort cherry-pick.", err=True)
                raise
            if delta.branch_exists():
                delta.delete_branch()
            delta.create_branch()


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


def get_config_paths():
    paths = []
    if is_inside_work_tree():
        root_path = Path(utils.run("rev-parse", "--show-toplevel").strip())
        paths = [root_path / ".dflock"]
    paths.append(Path("~/.dflock").expanduser())
    return paths


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
    if path is not None:
        paths = [path]
    else:
        paths = get_config_paths()
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
    ctx.obj["config"] = config


def cli_command(f):
    @cli_group.command
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except DflockException as exc:
            exc.handle_in_cli()

    return wrapper


def cli():
    try:
        cli_group()
    except subprocess.CalledProcessError as exc:
        click.echo(
            f"Subprocess failed. Captured output:\n{exc.output.decode()}\n{exc.stderr.decode()}\n",
            err=True,
        )
        raise


@cli_command
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
    help="Also detect the current plan and update the ephemeral branches.",
)
@click.option(
    "-f",
    "--force-push-without-lease",
    is_flag=True,
    type=bool,
    help="Force push without the --with-lease option.",
)
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    type=bool,
    help="Ask for confirmation before pushing each branch.",
)
@click.option(
    "-m",
    "--merge-request",
    is_flag=True,
    type=bool,
    help="Use Gitlab-compatible push-options to create a merge request.",
)
@click.option(
    "-c",
    "--change-request",
    nargs=1,
    type=str,
    default=None,
    metavar="INTEGRATION",
    help="Create a change request using the provided INTEGRATION.",
)
@inside_work_tree
@pass_app
@valid_local_commits
@remote_required
def push(
    app,
    delta_references,
    write,
    interactive,
    merge_request,
    change_request,
    force_push_without_lease,
) -> None:
    """Push deltas to the remote.

    The optional argument DELTA_REFERENCES is a list of delta references. If
    provided, only these deltas as pushed.

    If a delta reference is number (optionally prefixed by 'd') it resolves to
    the branch with that number in the output of dfl status.
    , checkout the delta branch
    that has that label in the output of "dfl status".

    If not a number, match against delta-branch names and if there is a unique
    match, checkout that branch.
    """
    tree = app.reconstruct_tree()
    if write:
        with utils.return_to_head():
            write_plan(tree)
        click.echo("Delta branches updated.")
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
                app.remote,
                merge_request=merge_request,
                without_lease=force_push_without_lease,
            )
            click.echo(f"Pushing {delta.branch_name}.")
            output = utils.run(*push_command)
            click.echo(output)
            if change_request is not None:
                click.echo(f"Creating change request for {change_request}.")
                command = app.create_change_request_command(
                    change_request, delta.branch_name, delta.target_branch
                )
                click.echo(f'Creating change request with "{command}"')
                subprocess.run(command, shell=True)


@cli_command
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
@valid_local_commits
@no_hot_branch
@undiverged
def plan(app, strategy, edit, show) -> None:
    """Create a plan and update ephemeral branches.

    The optional STRATEGY argument can be used to generate a plan. Available
    strategies are:

    \b
    detect (default): use the last-applied plan
    stack: create one delta per commit and make delta depend on the
             previous one
    flat: create one delta per commit
    empty: do not create any deltas

    Unless detect is used the previous plan will be overwritten.
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
    if not show:
        try:
            tree = app.parse_plan(new_plan)
            with utils.return_to_head():
                write_plan(tree)
            app.prune_local_branches(tree=tree)
            if len(tree) > 0:
                click.echo("Deltas written:")
                app.print_deltas({b: None for b in tree.keys()})
                click.echo(f'Run "dfl push" to push them to remote {app.remote}.')
        except (ParsingError, PlanError, CherryPickFailed) as exc:
            click.echo(f"Received plan:\n\n{new_plan}\n")
            exc.handle_in_cli()


@cli_command
@click.option(
    "-t",
    "--show-targets",
    is_flag=True,
    type=bool,
    help="Print target of each branch",
)
@inside_work_tree
@pass_app
@local_and_upstream_exist
def status(app, show_targets) -> None:
    """Show status of delta branches."""
    diverged = utils.have_diverged(app.upstream_name, app.local)
    if show_targets:
        tree = app.reconstruct_tree()
    else:
        tree = {b: None for b in app.get_delta_branches()}
    current_branch = utils.get_current_branch()
    if current_branch == app.local:
        click.echo("You are on the local branch.")
    elif current_branch in tree:
        click.echo("You are on an ephemeral branch.")
    else:
        click.echo("You are not on a branch known to dflock.")
    if diverged:
        click.echo("Your local and upstream branches have diverged")
    if len(tree) > 0:
        click.echo("\nDeltas:")
        app.print_deltas(tree, highlight=current_branch)
        click.echo(
            '\nRun "dfl checkout <delta number>" to check out an ephemeral branch.'
        )


@cli_command
@inside_work_tree
@clean_work_tree
@pass_app
@undiverged
@on_local
def remix(app) -> None:
    """Alias for "git rebase -i <upstream>".

    Only works when on local branch.
    """
    subprocess.run(f"git rebase -i {app.upstream_name}", shell=True)
    hot_branches = app.get_hot_branches()
    app.prune_local_branches(hot_branches=hot_branches)
    click.echo(
        'Hint: if you changed or amended commits, you need to run "dfl write" to '
        "update your delta branches."
    )


@cli_command
@inside_work_tree
@pass_app
@valid_local_commits
@on_local
@remote_required
def pull(app) -> None:
    """Alias for "git pull --rebase <upstream>".

    Only works when on local branch.
    """
    hot_branches = app.get_hot_branches()
    subprocess.run(f"git pull --rebase {app.remote} {app.upstream}", shell=True)
    app.prune_local_branches(hot_branches=hot_branches)


@cli_command
@inside_work_tree
@pass_app
@undiverged
def log(app) -> None:
    """Alias for "git log <local> ^<upstream>"."""
    if utils.get_current_branch() != app.local:
        click.echo("Warning: not on local branch.")
    subprocess.run(f"git log {app.local} ^{app.upstream_name}", shell=True)


@cli_command
@inside_work_tree
@click.argument("reference", required=False, default=None, type=str)
@pass_app
@local_and_upstream_exist
def checkout(app, reference) -> None:
    """Checkout deltas or the local branch.

    If REFERENCE isn't provided, "local", or the name of the local branch,
    checkout the local branch.

    Otherwise, REFERENCE is treated as a delta reference. If it is a number
    (optionally prefixed by 'd'), checkout the delta branch that has that label
    in the output of "dfl status".

    If not a number, match against delta-branch names and if there is a unique
    match, checkout that branch.
    """
    if reference in ["local", app.local, None]:
        branch = app.local
    else:
        branches = app.get_delta_branches()
        try:
            branch = resolve_delta(reference, branches)
        except ValueError as exc:
            raise click.ClickException(str(exc))
    subprocess.run(f"git checkout {branch}", shell=True)


@cli_command
@inside_work_tree
@pass_app
@no_hot_branch
@undiverged
def write(app) -> None:
    """Write ephemeral branches based on the current plan."""
    tree = app.reconstruct_tree()
    with utils.return_to_head():
        write_plan(tree)
    if len(tree) > 0:
        click.echo("Deltas written")
        app.print_deltas({b: None for b in tree.keys()})
        click.echo(f'Run "dfl push" to push them to remote {app.remote}.')
    else:
        click.echo('No deltas found. Run "dfl plan" to create them.')


@cli_command
@click.option("-y", "--yes", is_flag=True, help="Do not ask for confirmation.")
@pass_app
@inside_work_tree
@local_and_upstream_exist
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


@cli_command
@inside_work_tree
def init() -> None:
    """Interactively configure dflock."""
    paths = get_config_paths()
    for path in paths:
        if path.exists():
            click.echo(f"Note: existing config found at {path}.")
    root_path = Path(utils.run("rev-parse", "--show-toplevel").strip())
    upstream = click.prompt("Name of your upstream branch?", default=DEFAULT_UPSTREAM)
    local = click.prompt("Name of your local branch?", default=DEFAULT_LOCAL)
    remote = click.prompt("Name of your remote?", default=DEFAULT_REMOTE)
    editor = click.prompt("Command for invoking your editor?", default=DEFAULT_EDITOR)
    config_path = root_path / ".dflock"
    click.confirm(
        f"Continue to write provided values to {config_path}?", abort=True, default="Y"
    )
    config = configparser.ConfigParser()
    with open(config_path, "w") as f:
        config["dflock"] = {
            "upstream": upstream,
            "local": local,
            "remote": remote,
            "editor": editor,
        }
        config.write(f)
