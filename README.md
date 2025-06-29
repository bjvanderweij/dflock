# dflock

Dflock is a tool that helps you submit several interrelated features for review while you do all of your work on a single branch.

Dflock stands for *delta flock* because it allows you to herd a flock of deltas.

It supports workflows like stacked-diffs transparantly in projects that use branch-based MR/PR operations.

Terminology:

Local branch: the branch on which you do your every-day development. This could be a special branch called `<your-name>-WIP` or it could be your local copy of `main`.

Upstream: the repository's main branch into which your local work is eventually integrated.

Local commits: the commits that are on your local branch but have not been integrated into the upstream branch yet.

Delta: an independently reviewable set of changes. A changeset consists of one or more commits. These commits may but need not be contiguous in your local commits.

Change request: this terminology is borrowed from git-spice: a request to integrate a delta into the upstream. Usually this is what triggers CI/CD pipelines and external review.

Ephemeral branch: a branch created by dflock to serve a change request.

## What does it do?

Essentially, dflock automates tedious git-housekeeping required if you want to stack change requests without using a dedicated platform. It cherry-picks commits into ephemeral branches that serve as the basis for change requests.

Dflock aims to practice minimalism in a few ways:

* it does not aim to replace git and only steps in where using just git would be tedious.
* it does not aim to replace Github, Gitlab, etc. (you don't have to convince your collaborators of anything)
* all of its actions and manipulations correspond to relatively simple git operations
* the only local state it stores are a set of ephemeral git branches

Furthermore, it provides a set of aliases provide names to common git operations in a [branchless workflow](#workflow).

## Division of responsibilities

As a developer, you only worry about a single lineage of local commits and about the dependencies between those commits. You are responsible for squashing, re-ordering your commits lineage into a shape suitable for merging.

By dependencies, I mean the following: if two `1`, and `2` commits can be swapped in order (e.g., using `git rebase --interactive`) without conflicts they are independent. If they cannot, that usually means `2` builds further on top of changes in `1`. Though you can be unlucky and have the situation where the changes in `2` are two close to the changes `1` causing git to mark them as conflicting.

The tool, dflock, then manages creating and updating ephemeral branches for change requests. A key point is that you never need to work on or switch to these branches. You can do all work in your local branch.

I found that after using this workflow for a while, the absolute order of commits loses prominence in my mental model and is replaced by the dependency relations. If two commits can be swapped in an interactive rebase, they are independent.

## How does it compare to other tools in this space?

Over the past few years a number of other tools have cropped up that address a similar problem.

### Ghstack

Dflock is similar to ghstack in that it creates branches and selectively cherry-picks local commits into them.

It allows you to specify declaratively how you want to combine your commits into pull/merge requests, and how these
What it does differently from ghstack is that it uses its local branches

It currently provides less integration with the Github API and works well with Gitlab. It can create PR/MRs for you but is otherwise not aware of their existence.

### Git-spice

I have not used git-spice. Git-spice allows you to manage DAGs of changes. Git-spice then offers you the tools to move around in this DAG and make changes. By contrast, dflock does not encourage moving around in the DAG or to create branches. Instead it encourages you to manage all your changes in a single lineage of commits and let dflock handle the creation of branches. Another notable difference is that local-state is only stored as git branches, whereas git-spice stores JSON under a special ref.

Git-spice uses terminology *Change Request* where dflock uses the term *delta*.

### Phabricator

I have not used phabricator, but it appears that phabricator aims to replace your interaction with git by interaction with phabricator, which is explicitly not

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

Dflock does care how you address reviewer comments. That is you can amend commits or create separate commits that you insert into your lineage of local commits.

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

### Dflock operations

Plan: detect and edit the current integration plan. This is where the most complex logic and automation happens. All other commands (except perhaps write and push are essentially convenient shortcuts).

Write: create or update the ephemeral branches according to the current integration plan.

Push: push local branches to the remote and optionally create change requests.

Pull:

Checkout:

Log:

Remix: an alias for `git rebase --interactive <upstream>`.

Reset: reset the plan by deleting all ephemeral branches associated with the current local commits.

Status: show existing ephemeral branches and their indices.

## Workflow

Dflock was designed with a specific workflow in mind.

The core idea of this workflow is to do all work on a single, *local* branch that is ahead of an *upstream* branch.
The upstream branch can for example be `origin/main` while your local branch is `main`.
Instead of working on `main` you could also create a personal "work-in-progress" branch.
That might be useful if you want to push your work to a remote from time to time.

You develop features in one or more *local commits* on your local branch.
Periodically, you request review for one or more of these commits by creating temporary branches
When approved, they are integrated into the *upstream* by doing a fast-forward merge.

You can rebase your local branch on your *upstream* branch by running:

```
git pull --rebase origin/main
```

This will integrate the commits that have been approved and integrated into `origin/main` along with work by your team-mates into your local `main`.

You are largely free in how organize your work in local commits.
Local commits could, but don't have to, correspond to individual features.
Since they are local, you can also freely amend and re-order these commits with `git rebase`.

The part of this that is tedious is managing and updating temporary branches from which integration requests (pull requests or merge requests) are created.
This is where dflock comes into play.

Suppose that you have the following commits.

```
c0 initial commit
c1 update readme <-- origin/main
c2 feature 1
c3 feature 2 (work in progress)
c4 feature 3 <--- main
```

Suppose that we want to publish "feature 1" and "feature 2".
We can create an "integration plan" with

```
dflock plan -e
```

The `-e` flag causes an editor to launch showing our local commits.

```
s c2 feature 1
s c3 feature 2
s c4 feature 3 (work in progress)
```

This can be read as a sequence of instructions representing an "integration plan". This editor-based interface is inspired by the `git rebase --interactive` command. The "s" command means skip or do not use this commit. To publish a commit for review, change "s" into a "b", optionally followed by a numeric label.

```
b0 c2 feature 1
b1 c3 feature 2
s c4 feature 3 (work in progress)
```

After saving and closing, dflock asks you to confirm that you want to create branches based on this plan.

After doing so, it will create two feature branches both starting from your upstream branch (origin/main).
The names of these branches are based on the commit message of the first (or last - this is configurable) commit of the feature.

Finally, publish your changes with `dflock push`. This force-pushes each of branches dflock created to your remote.
Optionally, you can create integration requests with the `-m` flag. This currently only works for Gitlab.

Dflock will remember your integration plan. The next time you run `dflock plan`, dflock recovers the integration plan based on the branches it created and the commits messages of your local commits.

### Multiple commits in a feature

You're not limited to creating integration requests that consists of single commits (although it [may not be a bad idea to do so](https://jg.gg/2018/09/29/stacked-diffs-versus-pull-requests/)). For example, the plan below bundles feature 1 and feature 2 in a single integration request.

```
b c2 feature 1
b c3 feature 2
s c4 feature 3
```

This plan creates a single feature branch containing `c2` and `c3`.

### Complex dependencies

Often, some but not all of your features might depend on each other. Dflock lets you specify more complex dependency relations between features. For example, in a "stacked diffs" workflow, you stack multiple diffs on top of each other and create integration requests.

Use `dflock plan stack` to create a stack of integration request where each integration request depends on the previous one.

```
b0 c2 feature 1
b1@b0 c3 feature 2
b2@b1 c4 feature 3
```

The syntax "b1@b0" means: create a feature b1 that depends on b0. It will result in a feature branch

However more complex dependency relationships are also possible. It might be that feature 2 and feature 3 are independent features that can both require b0 to be integrated first.
The plan below represents this situation.

```
b0 c2 feature 1
b1@b0 c3 feature 2
b2@b0 c4 feature 3
```

## How does it work?

Dflock uses git plumbing commands under the hood.

Branch names for deltas are chosen based on either the first or last commit of that delta (depending on configuration, first is default). The branch name is a combination of the first few words of the commit message and a short hash of the entire commit message. By looking at the local commit messages and the currently existing branches, dflock can reconstruct the plan that created the branches, provided that there are no duplicate commit messages and that the commit messages of your local commits did not change.

Ephemeral branch-names are unlikely to clash with existing branch names, which is important because they are often force-pushed to a remote.

The process for creating ephemeral branches for change requests works roughly as follows: Dflock iterates through your deltas in chronological order. For each delta, it checks out the target branch (which is either the upstream or must already exist because of the chronological order). It then creates the ephemeral branch for that delta. If the ephemeral branch already exists it is deleted first. Finally it cherry-picks the commits belonging to the delta into the ephemeral branch.

Dflock never touches your local branch or commits. It only creates ephemeral branches and cherry-picks commits.

# Repository configuration

For an optimal experience, it's recommended you enable the following settings. For both Gitlab and Github, configure:

1. auto-delete integration request branch (source branch in Gitlab, head branch in Github) after merge
2. only allow fast-forward merges into upstream

Setting 1) ensures that when you have `B -> A -> main` and you merge `A`, the target/base branch of `B` is updated to the target/base branch of `A`, namely `main`.

Setting 2) ensures that running `git pull --rebase origin main` will auto-detect already applied commits.

## Snags

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

Dflock can automatically create change requests for you via a extensible mechanism.

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
-
