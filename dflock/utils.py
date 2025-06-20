import subprocess
import uuid
from pathlib import Path
from contextlib import contextmanager


class CalledProcessError(subprocess.CalledProcessError):
    pass


def run(*git_action: str, cwd=None, check=True):
    # print(" ".join(git_action))
    try:
        # print(" ".join(git_action))
        result = subprocess.run(
            ["git", *git_action], check=check, capture_output=True, cwd=cwd
        )
    except subprocess.CalledProcessError as exc:
        # print(f"stdout: {exc.stdout.decode()}.")
        # print(f"stderr: {exc.stderr.decode()}.")
        raise
    return result.stdout.decode("utf-8")


def get_local_branches() -> list[str]:
    result = run("for-each-ref", "--format=%(refname:short)", "refs/heads/")
    return result.strip().split("\n")


def get_repository_root() -> Path:
    result = run("rev-parse", "--show-toplevel")
    return Path(result.strip())


def get_head() -> str:
    with open(get_repository_root() / ".git" / "HEAD") as f:
        head = f.read().strip()
    if head.startswith("ref: "):
        ref = head.split()[1]
        assert ref.startswith("refs/heads/")
        return ref[len("refs/heads/"):]
    return head


def object_exists(rev):
    try:
        run("rev-parse", "--verify", rev)
    except subprocess.CalledProcessError as exc:
        if exc.returncode == 128:
            return False
        raise
    return True


def checkout(*args):
    run("checkout", *args)


def have_diverged(rev_a, rev_b):
    rev_list_1 = run("rev-list", "--format=oneline", f"{rev_a}..{rev_b}")
    rev_list_2 = run("rev-list", "--format=oneline", f"{rev_a}...{rev_b}")
    return rev_list_1 != rev_list_2


def get_current_branch():
    return run("rev-parse", "--abbrev-ref", "HEAD").strip()


@contextmanager
def temporary_branch():
    head = get_head()
    name = uuid.uuid4().hex
    run("checkout", "-b", name)
    try:
        yield
    finally:
        checkout(head)
        run("branch", "-D", name)


@contextmanager
def return_to_head():
    head = get_head()
    try:
        yield
    finally:
        checkout(head)
