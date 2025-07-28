# Dflock

Dflock is a git-complementing tool that automates the tedious parts of diff-stacking on platforms that use branch-based [change-requests](#change-requests) such as Gitlab and Github (but see [snags](#are-there-any-snags) for Github).

It is designed specifically for a workflow in which all work happens on a single branch and commits are periodically and selectively submitted to change requests.

## What does dflock offer?

Dflock offers the following:

* Support for a [workflow](#what-is-this-workflow-you-speak-of) in which you never create branches
* Smoothly creating multiple change requests at once
* Flexibly stacked change requests
* Interaction via your favourite text editor

Dflock uses git under the hood and adds a thin layer of abstraction. It aims to complement git, not replace it.
You can use it together with git and collaboration platforms like Github and Gitlab, although is has only been tested extensively it with Gitlab.

## What does it do?

Dflock's main specialty is translating a text-based plan specifying dependencies between commits into a set of (optionally stacked) change requests.

The plan specifies how to divide these commits over one or more change requests and in what order these change requests can be integrated.
It looks a bit like the interface of git interactive rebase. Here's an example of such a plan.

```git
d0 0001b3a Update README with overview of commands
d1 1dc86f8 Add functionality to update change requests to App class
d2@d1 9ee1334 Add --update-change-request flag to push command
```

It contains three commits and instructs dflock to create three branches and try to cherry pick commits into them: `d0` will contain commit `0001b3a`, `d1`, will contain commits `1dc86f8`, and `d2` will contain commits `1dc86f8` and `9ee1334`.
This will be successful if the changes in `d1` are independent from the changes in `d0`.
These branches can be used to create three change requests: change requests `d0` and `d1` have the upstream branch as they target branch, while `d2` has the `d1` as its target branch.
Note that `d0` and `d1` can be integrated in any order, but `d2` requires `d1` to be integrated first (or to be integrated in `d1`).

Dflock remembers the plan, even after more commits are added or some change requests have been integrated.
Its footprint is light: the only information dflock needs is the names of the branches it created and the commits they contain.

## How do I install and use it?

Install dflock by cloning the repository or using pip:

```
pip install dflock
```

Go to the repository of the project in which you want to use dflock.

To configure a custom local branch, upstream branch (learn more about the [workflow](#what-workflow-does-dflock-support) to understand these concepts), and text editor for interaction, type

```
dfl init
```

Now you can start committing to your local branch. To create change requests, use

```
dfl plan
```

to bring up the [integration plan](#the-integration-plan).

If the branches have been created successfully, you can push them with

```
dfl push
```

On the collaboration platform you use you can now create change requests manually. To show an overview of branches and target branches created by dflock, use

```
dfl status --show-targets
```

For some platforms dflock can create change requests automatically. See [this section](#can-dflock-automatically-create-change-requests) for more information.

To learn more about how to make effective use of dflock, see the [recommended workflow](what-workflow-was-dflock-built-for).

## What workflow was dflock built for?

Dflock was built for a workflow in which almost all work is done on a single branch, called the [*local*](#local) branch.
This branch tracks an [*upstream*](#upstream) branch, into which your work aspires to be integrated via [*change requests*](#change-requests).
Your local branch is usually a few commits ahead of the upstream.
These commits are your [*local commits*](#local-commits).
Your local commits usually consist of in-progress work and work awaiting review and approval.

### Development of changes

Changes are committed incrementally to the local branch. There is no need to create branches for new features. When one feature is finished, you simply continue committing to the same branch.

### Submitting change requests

To create change requests, you periodically use `dfl plan` bring up the [*integration plan*](#integration-plan) and selectively assign sets of commits ([*deltas*](#delta)) to change requests and specify their inter-dependencies.
Based on the plan, dflock will create one [*ephemeral branch*](#ephemeral-branch) per change request and cherry-pick commits into it.

Importantly, ephemeral branches only exist to serve change requests.
You generally do not commit to or manipulate ephemeral branches directly because dflock may delete them when they are no longer needed.
This happens for example after the change request has been integrated.
All changes originate from the local branch, flowing via ephemeral branches into the remote upstream.

When the change requests are ready for submission, use `dfl push` to push them to the remote. Dflock offers some support for automaticaly creating change requests on Gitlab or Github as described [below](#automatic-change-request-creation).

### Amending previous changes

When making changes to published change requests, for example to address reviewer comments, you are free to use whatever method you prefer to re-order, amend or drop local commits.
After amending commits used in change requests, you can use `dfl write` to update the ephemeral branches.
If you instead want to add updates to a change request as extra commits, you can use `dfl plan` to do so.

### Incorporating upstream changes

Once change requests have been integrated into the upstream branch, you can update the local branch using `dfl pull`.
This performs a `git pull --rebase <remote> <upstream>` and prunes ephemeral branches.
The same method can be used to pull in changes integrated into the upstream by others.

## The integration plan

Integration plans are a central concept in dflock. Typing `dfl plan` brings up a text editor showing the current integration plan. Each line of the plan consists corresponds to a commit and consists of a command, a truncated commit checksum, and the first line of the commit message.

The command starts either with `d` to add the commit to a delta or `s` to skip it. To distinguish different deltas, an optional numeric label can be given. E.g., `d0` and `d1` create different deltas. To specify a dependency, the `@` symbol followed by a delta label is used. E.g., `d1@d0` creates a delta that depends on `d0`.

### Example plans

In the plans below, commit checksums have been replaced by the numbers 0, 1, and 3, and commit messages which would be shown by `dfl plan` are omitted.

#### Selectively added commits

This plan creates a single change request containing commit 1.

```
s 0 ...
d0 1 ...
s 2 ...
```

#### Multiple commits in one change-request

This plan creates a single change request containing commit 1 and 2.

```
s 0 ...
d0 1 ...
d0 2 ...
```

#### Non-contiguous commits in one change-request

Commits in a plan don't need to follow each other sequentially.

This plan creates a single change request containing commit 0 and 2.

```
d0 0 ...
s 1 ...
d0 2 ...
```

#### Fully independent change requests

This plan creates three fully independent change requests that can be integrated into the upstream branch in any order.

```
d0 0 ...
d1 1 ...
d2 2 ...
```

#### Fully stacked change requests

This plans creates three change requests that are "fully stacked". That is, each change request requires the previous one to be integrated first.

```
d0 0 ...
d1@0 1 ...
d2@1 2 ...
```

### Syntactical rules

Since plans are edited in a text editor their syntax is designed to require a minimal number of edits, while maintaining unambiguousness.

#### Delta-labels can be ommitted

An omitted label also distinguishes deltas.

```
d 0 ...
d0 1 ...
```

is the same as

```
d0 0 ...
d1 1 ...
```

and

```
d 0 ...
d1@ 1 ...
```

is the same as

```
d0 0 ...
d1@d0 1 ...
```

#### The `d` prefix can be omitted when referring to deltas after `@`

The commands `d1@d0` and `d1@0` are equivalent.

####  Skipping a commit is the same as deleting the entire line.

```
s 0 ...
d1 1 ...
```

is the same as

```
d1 1 ...
```

#### The target-branch needs to be specified only once in change requests consisting of multiple commits.

```
d0 0 ...
d1@d0 1 ...
d1@d0 2 ...
```

is the same as

```
d0 0 ...
d1 1 ...
d1@d0 2 ...
```

### Limitations

Currently, dflock imposes some limitations on what plans can be specified. These constraints are not inherent to the workflow and might be lifted in future versions of dflock.

#### A change-request cannot depend on multiple change requests.

The only way to make d2 depend on both d0 and d1 is to fully stack them:

```
d0 0 ...
d1@d0 1 ...
d2@d1 2 ...
```

#### A change request occurring after another change request cannot have a dependency that occurring before the dependency of the last change-request.

This is not possible:

```
d0 0 ...
d1@d0 1 ...
d1 2 ...
```

Note that a change-request with no specified dependency has an implicit dependency on the upstream.

It these situations it is always possible to use `dfl remix` to re-order the commits such that a valid plan can be constructed.

For example, in the plan above, if commit 2 is truly independent from the others as implied by the plan, it can be swapped with commit 1 to construct the following valid plan:

```
d0 0 ...
d1 2 ...
d1@d0 1 ...
```

## How should I set up Gitlab or Github?

I found the following settings to work well with dflock's workflow:

For both Gitlab and Github, configure:

1. auto-delete change request branch ("source branch" in Gitlab, "head branch" in Github) after merge
2. only allow fast-forward merges into upstream

Setting 1) ensures that when you have `B -> A -> main` and you merge `A`, the target/base branch of `B` is updated to the target/base branch of `A`, namely `main`.

Setting 2) ensures that running `git pull --rebase origin main` will auto-detect already applied commits.

## Does dflock need configuring?

Dflock comes with a default configuration. In this configuration, both the local and upstream branch are assumed to be the main branch.

You can provide custom configuration in a file called `.dflock` placed either in your home directory (for cross-project configuration) or the root folder of a git repository (for per-project configuration). In the latter case, it's best to add `.dflock` to `.gitignore` since it contains personal configuration.

You can generate a project-local configuration interactively by running `dfl init`.

## Can dflock automatically create change requests?

Yes, dflock has rudimentary for automatic change-requests creation. It also provides a mechanism for extending this with custom commands.

### Gitlab merge requests

To create Gitlab you have two options: By default, `dfl push` supports the `--merge-request` flag which will use [git push options](https://docs.gitlab.com/topics/git/commit/#push-options) to trigger merge-request creation when pushing to gitlab.

Alternatively, you can add a custom integration, for example using the `glab` CLI. To do so, add the following to your [`.dflock` configuration](#configuration) file.

```
[integrations.gitlab]
change-request-template=glab mr create --source-branch {source} --target-branch {target}
```

To use this template in `dfl push`, invoke it with `--change-request github`.

### Github pull requests

For github, you can create a custom change-request integration that uses the `gh` CLI tool. To do so, add the following to your `.dflock` configuration file.

```
[integrations.github]
change-request-template=gh pr create --head {source} --base {target}
```

To use this template in `dfl push`, invoke it with `--change-request github`.

## What commands does dflock support?

### Plan

`dfl plan`

Detect and edit the current integration plan. This is operation automates the most complex parts of the workflow. It detects the integration plan from existing local branches and creates or updates ephemeral branches for change requests. Most other commands are essentially convenient shortcuts for common git commands.

### Write

`dfl write`

Detect the current integration plan and create or update the ephemeral branches accordingly. Normally `dfl plan` performs this operation, but `dfl write` is useful when the plan has not changed but you've amended or re-ordered commits in your local branch.

### Push

`dfl push`

Push ephemeral branches to the remote and optionally create change requests.

### Pull

`dfl pull`

Update your local branch. Shortcut for `git pull --rebase <remote> <upstream>`, but performs additional branch-pruning afterwards.

### Remix

`dfl remix`

Edit the local commit history with git interactive rebase. Shorthand for `git rebase --interactive <upstream>`, but performs additional branch-pruning afterwards.

### Log

`dfl log`

Show a git log containing only local commits. Shorthand for `git log <local> ^<upstream>`.

### Status

`dfl status`

Show current ephemeral branches and whether they are up to date with the remote.

### Checkout

`dfl checkout`

Perform a `git checkout` on the local branch or an ephemeral branch. As a shortcut, the ephemeral-branch indices shown by `dfl status` can be used here, or a substring of the branch name if it resolves to a unique branch.

### Reset

`dfl reset`

Reset the integration plan by deleting all ephemeral branches associated with the current local commits.

## Are there any snags?

### Integrating stacked change requests causes conflicts in Github

When creating pull requests based on the plan below, two branches are created: one containing commit 0, and one containing commits 0 and 1.

```
d0 0 ...
d1@d0 1 ...
```

After merging the first pull-request (containing commit 0), Github unfortunately does not recognize that commit 0, now added to the upstream, does not conflict with commit 0 in the second pull request and marks it as a conflict.

This is seriously hampers the usefulness of this workflow in Gitlab.

Gitlab does not have this issue.

### Github does not allow pull request dependencies

A Github pull request offers no way to block merging it before another pull request has been merged. Gitlab does support this, although dflock's default automatic merge request creation mechanism does not currently populate this field.

### Not pushing all deltas leads to incorrect diffs and conflicts

Consider the following plan:

```
d0 0 ...
d1@d0 1 ...
```

In our change requests we expect the diff of the first change request to show the changes in commit 0 and the diff of the second change request to show the changes in commit 1.

However if we update and push only the second change request, the commit checksum of commit 0 in `d1`'s ephemeral branch will change. As a result the diff shown in the change request might include the changes from commit 0 because the commit in the target branch is no longer recognized as commit 0.

This happens because any update to the integration plan causes dflock to re-write the ephemeral branches. Since that process relies on cherry-picking, the commit checksums change upon each write.

Visually, upon pushing d0 and d1, the situation on the remote is as follows:

```
0 --> 1
|     |
d0    d1
```

After update commit one (creating commit 1') and cherry-picking commits 0 and 1' the following situation is created on the remote:

```
0
|
d0

0' --> 1'
       |
       d1
```

### Frequent updating of change requests

Trying to avoid the issue of [incorrect diffs when not pushing all deltas](#not-pushing-all-deltas-leads-to-incorrect-diffs) causes a change request to be updated each time a downstream change request is updated - even though nothing changed.

This might be undesirable for various reasons including spurious notifications sent to change request reviewers or unnecessary triggering of slow or expensive CI/CD pipelines.

### Limitations of automatic change request creation

#### Gitlab

As already mentioned, dflock only configures the target branches and does add dependencies on other merge requests to the created merge request.

#### Gitlab and Github

If dependencies are changed by an updated integration plan and merge requests have already been created, the target branches of the merge requests are not updated automatically.

## Why is it called dflock?

The name dflock derives from *delta flock* because the tool allows you to herd a flock of deltas.

## Glossary

### Local

The branch used for development. This could be a personal branch called `<your-name>-WIP` (which is safe to force-push to the remote) or it could be your local copy of `main` (which should obviously not be pushed to the remote).

### Upstream

The remote branch into which commits on your local branch aspire to eventually be integrated. Often the main branch of the repository.

### Local commits

Commits you are working on that are only on your local branch and not in the upstream. More precisely: commits reachable from the local branch, but not from upstream branch.

### Integration plan

A text-based representation of a tree-like structure that instructs dflock which deltas to construct and how they depend on each other. See [this section](the-interation-plan) for more discussion of integration plans.

### Delta

A set of changes represented by one or more commits.

### Change request

A request to integrate a set of commits (a delta) into the upstream. Gitlab and github call this merge requests and pull requests respectively.

### Ephemeral branch

A branch containing a delta created by dflock for a change request. It's called ephemeral because it only serves to create a change request and dflock may delete the branch when it's no longer needed.
