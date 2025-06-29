# dflock

Dflock is a utility that wraps around git to support a workflow in which you perform most of your work on a single branch and periodicaly submit [change-requests](#terminology).

This workflow is related to "stacking", but combines this with a workflow in which you rarerly create branches.
It supports arbitrary depedeny structures between change requests. It supports branch-based change requests like Github's pull request or

The name dflock derives from *delta flock* because it allows you to herd a flock of deltas.

## What does this do?

Essentially, dflock automates tedious git-housekeeping required if you want to stack change requests without specialized tooling. It cherry-picks commits into ephemeral branches that serve as the basis for change requests.

Furthermore, it provides a set of aliases provide names git operations that are common in a [branchless workflow](#workflow).

## Usage example

Here's how you could use `dfl` to contribute to this repository.

First, we clone the repository and create a branch called `wip` on which we'll do our local development.

```bash
git clone git@github.com:bjvanderweij/dflock.git
cd dflock
git checkout -b wip
```

Next, we make dflock aware of our local branch, the name of our remote (origin is the default, but explicit is better than implicit), the upstream (again, main is already the default), and our preferred editor, vim. Also, we'll add `.dflock` to gitignore since these are personal choices.

```
echo '[dflock]
remote=origin
local=wip
upstream=main
editor=vim
' > .dflock
echo '.dflock' >> .gitignore
```

Next, we'll do some development. Below we use `dfl` shortcuts for common git-operations. The corresponding git operations are annotated in the comments.

```
# Go to the local branch (equivalent: git checkout wip)
dfl checkout local
# Pull changes into our local (equivalent: git pull --rebase origin main)
dfl pull
# Make some changes
git commit -m "Update README"
# Make some further changes
git commit -m "Add update merge request functionality to \`App\`"
# Make some dependent changes
git commit -m "Add update merge request flag to push command"
# Found a typo in README changes
git commit -m "Fixup: Update README"
# Use the "fixup" directive to update our first commit (equivalent: git rebase --interactive origin/main)
dfl remix
```

Finally, we'll create a plan for integrating these changes into upstream.

```
dfl plan
```

This will open an editor showing our commits from top to bottom in chronological order (just like `git rebase --interactive`).

```
s 0 Update README
s 1 Add update merge request functionality to `App`
s 2 Add update merge request flag to push command
```

Commit hashes have for convenience been substituted with a chronological index.

The directive `s` indicates that the current plan is to "skip" this commit. That is, to not include it in any deltas.

To include commits into a delta, we use the `d` directive along with an optional numeric label to distinguish different deltas.

In our first commit, the change to README, is independent from the others and so we'll create a separate delta `d0` for it. We'll start a new delta `d1` for the next commit. We plan to submit `d1` as an separate change request, so we create another delta `d2` for the third commit. However, `d2` depends on changes in `d1`, so we indicate this dependency with `@` as follows: `d2@d1`.

```
d0 0 Update README
d1 1 Add update change request functionality to `App`
d2@d1 2 Add update change request flag to push command
```

After we save and exit, dflock will write attempt to cherry pick our commits into three branches off main, one containing commit `0`, one containing commit `1`, and one containing commit `1` and `2`. If any of the cherry picks fail, dflock will abort it and return to your local branch.

The names of the ephemeral branches are based on the commit messages of the first (or the last, if so configured) commit included in the delta. If the write is successful, this will allow dflock reconstruct the plan commit messages of your local commits and your local branches. In other words, the next time you run `dfl plan`, the editor will show the same plan (though numeric branch labels might change). If you delete one of the ephemeral branches, dflock will forget its delta.

If we want to see the ephemeral branches created by dflock, we can use

```
$ dfl status
On local branch.

Deltas:
  b0: update-readme-aebdb7c6 (not pushed)
  b1: add-update-merge-request-functionality-to-app-701bf48f (not pushed)
  b2: add-update-merge-request-flag-to-push-command-45866e69 (not pushed)
```

Finally, we push the branches created by dflock to the remote with the following command:

```
dfl push --merge-request
```

### Amending a change request

Dflock does not care how you address reviewer comments. That is you can amend commits or create separate commits that you insert into your lineage of local commits.

Imagine that in the example above we want to make a change to delta corresponding to the second commit. We could commit the change at the tip of our local branch and use `dfl remix` to place the commit directly after the second commit.

```
git commit -m "Address comments on update merge request functionality"
```

Running `dfl plan` again will now yield the following plan:

```
d0 0 Update README
d1 1 Add update change request functionality to `App`
s 3 Address comments on update merge request functionality
d2@d1 2 Add update change request flag to push command
```

We can add commit `3` to `d1` simply as follows:

```
d0 0 Update README
d1 1 Add update change request functionality to `App`
d1 3 Address comments on update merge request functionality
d2@d1 2 Add update change request flag to push command
```

After this, we can use `dfl push` to push the ephemeral branches to the remote.

Had we instead amended commit `1` we could simply use `dfl write` to cherry-pick local commits into the ephemeral branches.

## Configuration

Dflock will by default assume a reasonable configuration, but some things you may

## Operations overview

Below is a concise overview of operations supported by dflock.

### `dfl plan`

Detect and edit the current integration plan. This is operation automates the most complex parts of the workflow. It detects the integration plan from existing local branches and creates or updates ephemeral branches for change requests. Most other commands are essentially convenient shortcuts for common git commands.

### `dfl write`

Detect the current integration plan and create or update the ephemeral branches accordingly. Normally `dfl plan` performs this operation, but `dfl write` is useful when the plan has not changed but you've amended or re-ordered commits in your local branch.

### `dfl push`

Push ephemeral branches to the remote and optionally create change requests.

### `dfl pull`

Update your local branch. Shortcut for `git pull --rebase <remote> <upstream>`.

### `dfl remix`

Edit the local commit history with git interactive rebase. Shortcut for `git rebase --interactive <upstream>`.

### `dfl log`

Show a git log containing only local commits. Shortcut for `git log <local> ^<upstream>`.

### `dfl status`

Show current ephemeral branches and whether they are up to date with the remote.

### `dfl checkout`

Perform a `git checkout` on the local branch or an ephemeral branch. As a shortcut, the ephemeral-branch indices shown by `dfl status` can be used here, or a substring of the branch name if it resolves to a unique branch.

### `dfl reset`

Reset the integration plan by deleting all ephemeral branches associated with the current local commits.

## Terminology overview

**Local branch**: the branch on which you do your every-day development. This could be a special branch called `<your-name>-WIP` or it could be your local copy of `main`.

**Upstream**: the repository's main branch into which your local work is eventually integrated.

**Local commits**: the commits that are on your local branch but have not been integrated into the upstream branch yet.

**Delta**: an independently reviewable set of changes. A changeset consists of one or more commits. These commits may but need not be contiguous in your local commits.

**Change request**: this terminology is borrowed from git-spice: a request to integrate a delta into the upstream. Usually this is what triggers CI/CD pipelines and external review.

**Ephemeral branch**: a branch created by dflock to serve a change request.

## Workflow & terminology

Dflock was built for a specific workflow in which almost all work is done on a single branch.
Dflock calls this branch the *local branch*.
The local branch tracks an *upstream* branch, usually the main branch of the repository, but is usually a few commits ahead.
Dflock calls commits that exist on your local branch but not on the upstream *local commits*.
Local commits usually are a combination of changes awaiting review and work in progress.

Rather than creating and switching between branches, all work takes place on the local branch.
Periodically, you tell dflock which commits can be submitted for review.
Dflock creates what it calls *ephemeral branches* for and cherry-picks the commits into them.
These branches are called ephemeral because new commits and update to the change request in principle are never made on these branches.
They only serve *change requests*.
Dflock uses the neutral terminology change request for a request to integrate a set of changes represented consisting of one or more commits into the upstream.
Change requests correspond to merge requests in Gitlab and pull requests in Github.

If a change request needs amending, it is often possible to commit to the local branch and use interactive rebase to re-order the commits.

Once a change requests is accepted and integrated in the remote upstream, preferably via a fast-forward merge (see [repository configuration](#repository-configuration)), the local branch can be updated by fetching the upstream and rebasing the local.
The process for integrating changes made to the upstream by others is the same.

This process works smoothly because dflock never touches your local commits and only creates ephemeral branches.
Dflock remembers which commits belong to which change request by their commit messages.
That is why the local commits can be freely re-ordered or amended without disturbing open change requests.

This workflow is similar to "stacking" workflows in which multiple change requests are "stacked on top of each other".
It is different in the sense that it does not require change requests to be in a linear stack.
Every commit could be submitted as an independent change request, multiple commits can be added to a change request.
But also more complex graph-like dependency structures between change requests are supported.

Local commits could, but don't have to, correspond to individual features.
Since they are local, you can also freely amend and re-order these commits with `git rebase`.

## Does dflock have a philosophy?

Dflock aims to practice minimalism in several ways:

* it's intended to supplement git and not try to replace it: it steps in where using just git manually would be tedious
* it does not aim to replace Github, Gitlab, etc. (you don't have to convince your collaborators of anything)
* the actions it automates correspond all relatively simple git manipulations
* all of its local state is encoded in the git branches it creates

Its user-interface is to a significant extend outsourced to an editor of choice.

I hope this will especially please those of us who have invested in learning advanced text editing with vim or emacs.

## How does it work?

Dflock uses git plumbing commands under the hood.

Dflock never touches your local branch or commits. It only creates ephemeral branches and cherry-picks commits.

Names of ephemeral branches for deltas are consist of the first few words of a commit message on either the first or last commit of that delta (depending on configuration, first is default). The branch name is a combination of the first few words of the commit message and a short hash of the entire commit message. By looking at the local commit messages and the currently existing branches, dflock can reconstruct the plan that created the branches, provided that there are no duplicate commit messages and that the commit messages of your local commits did not change.

Ephemeral branch-names are unlikely to clash with existing branch names, which is important because they are often force-pushed to a remote.

The process for creating ephemeral branches for change requests works roughly as follows: Dflock iterates through your deltas in chronological order. For each delta, it checks out the target branch (which is either the upstream or must already exist because of the chronological order). It then creates the ephemeral branch for that delta. If the ephemeral branch already exists it is deleted first. Finally it cherry-picks the commits belonging to the delta into the ephemeral branch.

# Automatic change-request creation

# Repository configuration

For an optimal experience, it's recommended you enable the following settings. For both Gitlab and Github, configure:

1. auto-delete integration request branch (source branch in Gitlab, head branch in Github) after merge
2. only allow fast-forward merges into upstream

Setting 1) ensures that when you have `B -> A -> main` and you merge `A`, the target/base branch of `B` is updated to the target/base branch of `A`, namely `main`.

Setting 2) ensures that running `git pull --rebase origin main` will auto-detect already applied commits.

## Snags

### Rebasing

This workflow relies heavily on rebasing, which tends to be painless but can sometimes be a bit of a hassle. If you want to insert a commit `3` between `1` an `2`, the happy path is to simply commit at the tip of the local branch and use rebse to re-order the commits. Sometimes however, you want to make changes in a work tree that reflects commit `1`, for example when `2` makes changes in the same places as `3`. In that case, what I do is checkout `1` and go into "detached head" state, make the changes and commit `3`. Then I checkout local and rebase `2` on top of `3` (and address the merge conflicts).

The problem is not so much merge conflicts. Merge conflicts that arise while rebasing would have to be addressed at some point. The problem is that moving around the git tree is a hassle, requires careful attention and breaks your flow.

### Poor support from Github

Unfortunately, Github pull-requests do not recognize the situation where some of the commits of the head-branch have been merged into the main branch.

Take for example the following dependency structure :`B -> A -> main`. PR B merges into PR A and A targets main and we have two corresponding branches: `f_B`, containing commit `b` and `f_A` containing commit `a`. Branch `f_B` contains commits `[a, b]` and `f_A` contains `[a]`. If in Github we merge `f_A`, the PR for `f_B` will not recognize that `a` has been merged into `main` and argue that you have conflicts.

Gitlab is less strict in this case and will update `B` to contain only commit `b`.

### Partially pushing branches can lead to overlapping diffs

If we take the previous example where we have `B > A > main` and you've addressed some MR/PR feedback you may be tempted to force-push only `A` to the remote, especially if a push to a MR/PR triggers a costly CI/CD pipeline. However, doing this will break the continuity between `B` and `A` as the commits in `B` will no longer cleanly follow the commits in `A`. The result is that the diff that is presented to reviewers in `B` will include the changes from `A`.

This issue applies to both Github and Gitlab.

### Frequent updating of PRs/MRs

Because of the issue above, each update of a PR/MR needs to be accompanied by an update to all the dependent PR/MRs, even though nothing in their diff has changed. This may be undesirable if each update triggers and expensive CI/CD pipeline and/or noisy notifications for reviewers.

# Automatic integration request creation

Dflock has rudimentary support for automatic change-requests creation.

## Gitlab merge requests

For Gitlab you have two options. By default, `dfl push` supports the `--merge-request` flag which will use [git push options](https://docs.gitlab.com/topics/git/commit/#push-options) to trigger merge-request creation when pushing to gitlab.

Additionally, you can specify your own custom integration, for example using the `glab` CLI. To do so, add the following to your `.dflock` configuration file.

```
[integrations.gitlab]
change-request-template=glab mr create --source-branch {source} --target-branch {target}
```

To use this template in `dfl push`, invoke it with `--change-request github`.

## Github pull requests

For github, you can create a custom change-request integration that uses the `gh` CLI tool. To do so, add the following to your `.dflock` configuration file.

```
[integrations.github]
change-request-template=gh pr create --head {source} --base {target}
```

To use this template in `dfl push`, invoke it with `--change-request github`.

# Snags

- Github
    - Conflicts issue: First merge all MRs into one big one and them merge that?
    - Cannot specify dependencies in github
- Gitlab
    - Specifying depedencies is manual

- If you change the DAG structure and have already created MRs you need to reconfigure the target branches
    - The mr create/update script should
        - check if an MR exists for a branch exists update it if so
- [blog] Updating commits when there are significant conflicts afterwards is a bit of a hassle
    - need to checkout commit, amend or commit, then rebase and remember to remove the commit
