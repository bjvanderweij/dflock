# Dflock

Dflock is a tool that helps you work on multiple features on a single branch and submit them for review flexibly.

It supports using workflows like stacked-diffs transparantly in projects that use Gitlab.

## What does it do?

Dflock tries to practice minimalism: it does not aim to replace git and only steps in where using just git would be tedious.

## How to use it



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

## How it works

Dflock is careful never to touch your local branch or commits.
Instead, it creates ephemeral feature branches and cherry-picks the relevant commits into them.
These dflock-managed branches are the only git objects that dflock writes to.
They are ephemeral because are deleted and recreated each time you save an integration plan.
As such, you should never do any work on directly on these branches.

The feature branches are named in a way that makes it unlikely for them to name-clash with other branches.
This is imporant because they are often force-pushed to your origin.

Dflock remembers your dependency tree, but does not store any state directly in files. Its "memory" is encoded entirely in the *commit messages* of your local commits and the *branch names* of the branches that dflock creates. If you amend the commit message of local commits, dflock will not remember what feature they belong to. Dflock will complain there is a duplicate commit message among your local commits.
