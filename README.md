# Dflock

Dflock is a git-complementing tool that automates the tedious parts of diff-stacking on platforms that use branch-based [change-requests](#change-requests) such as Gitlab.

It enables a workflow in which all work happens on a single branch and commits are periodically and selectively submitted to change requests.

Dflock's main features are:

* Support for a [workflow](#what-is-this-workflow-you-speak-of) in which you never create branches
* Submitting your work as small independent or stacked change requests
* Interaction and control via a text editor with [integration plans](#integration-plans)

You can use dflock and git together. Dflock aims to complement git, not replace it.

You can [use dflock to created stacked merge requests in Gitlab](). This works quite well, although [there are snags](#are-there-any-snags).
It might be useful with Github as well, but I have not tested this. There are some [clear challenges](#are-there-any-snags) with using stacked pull requests in Github.

## Who is it for?

Developers who want to stack change requests, have a good understanding of git, and are comfortable editing git history.

Dflock can fit into conventional merge- or pull-request-based workflows and works with widely used platforms like Gitlab and Github. There is no need to convince collaborators to switch platforms or workflows.

## What does it do?

Dflock's main specialty is translating a text-based plan that indicates which commits should end up in which change request.
If there are dependencies between commits, then change requests can be stacked.
However, sometimes commits are independent, and the corresponding change requests can point directly to the upstream.

As an illustration, here's an example of a plan.
It looks a bit like the plan for an interactive rebase in git.

```git
d0 0001b3a Update README with overview of commands
d1 1dc86f8 Add functionality to update change requests to App class
d2@d1 9ee1334 Add --update-change-request flag to push command
```

This plan covers three commits. It tells dflock that commits `0001b3a` and `1dc86f8` are independent, and that commit `9ee1334` depends on the previous commit.
Based on this, dflock will create three branches: `d0` containing commit `0001b3a`, `d1`, containing commits `1dc86f8`, and `d2` containing commits `1dc86f8` and `9ee1334`.
To do this, dflock uses cherry-picking.
This plan will execute successfully only if the changes in the second commit indeed do not change parts of files that were changed in the first commit.

The created branches can be used to create three change requests: change requests `d0` and `d1` have the upstream branch as they target branch, while `d2` has the `d1` as its target branch.
Note that `d0` and `d1` can be integrated in any order, but `d2` requires `d1` to be integrated first (or to be integrated in `d1`).

Dflock remembers the plan, even after more commits are added or some change requests have been integrated.
Its footprint is light: the only information dflock needs is the names of the branches it created and the commits they contain.

## How do I install and use it?

Install dflock by cloning the repository or using pip:

```
pip install dflock
```

Now you can navigate to your project's repository and start using dflock.

You'll most likely want to customize dflock's default configuration options such as the local branch to use, the upstream branch, and which text editor to use for editing plans (to learn more about these concepts, look into dflock's [workflow](#what-workflow-does-dflock-support)). For this, you can invoke dflock's interactive configuration with

```
dfl init
```

Having committed some work to your local branch, you can create change requests, using

```
dfl plan
```

to bring up the [integration plan](#the-integration-plan).

If the plan executes successfully, you inspect the created branches with:

```
dfl status
```

To push the branches to the remote, use

```
dfl push
```

You can also selectively push branches using their index in the output `dfl status`. To push only the first branch, use

```
dfl push 0
```

Dflock can create change requests automatically while pushing branches to some platforms. See [this section](#can-dflock-automatically-create-change-requests) for more information.

Otherwise, you can use the pushed branches to create change requests manually. To see an overview of branches and target branches created by dflock, use

```
dfl status --show-targets
```

## What workflow can I use with it?

Dflock was built for a workflow in which almost all work is done on one branch, called the [*local*](#local) branch.
This branch tracks an [*upstream*](#upstream) branch, into which your work aspires to be integrated via [*change requests*](#change-requests).
Your local branch is usually a few commits ahead of the upstream.
These commits are your [*local commits*](#local-commits).
Your local commits are usually a mixture of work-in-progress and commits awaiting review and approval.

### Development of changes

Changes are committed incrementally to the local branch. There is no need to create branches for new features. When one feature is finished, you simply continue committing to the same branch.

### Submitting change requests

To create change requests, you periodically use `dfl plan` bring up the [*integration plan*](#integration-plan) in which you selectively assign sets of commits ([*deltas*](#delta)) to change requests and specify their inter-dependencies.
Based on the plan, dflock will create an [*ephemeral branch*](#ephemeral-branch) for each change request and cherry-pick the selected commits into them.
Dflock remembers the integration plan. In case you need to refine or edit it, you can run `dfl plan` again to bring up the integration plan you previously created.

Importantly, ephemeral branches exist only to serve change requests.
You generally do not commit to or manipulate ephemeral branches directly because dflock cleans up these branches when they are no longer needed.
This happens for example after the change request has been integrated.
All changes originate from the local branch, flowing via ephemeral branches into the remote upstream.

When the change requests are ready for submission, use `dfl push` to push them to the remote. Dflock offers some support for [automaticaly creating change requests on Gitlab or Github](#automatic-change-request-creation). You can [stack merge requests in Gitlab](#how-do-i-stack-merge-requests-in-gitlab), but Github, at the time of writing, does not support stacking pull requests very well.

### Amending change requests

When making changes to published change requests, for example to address reviewer comments, you are free to use whatever method you prefer to re-order, amend or drop local commits.
To this end, dflock provides a convenient command, `dfl remix`, which invokes `git rebase --interactive <upstream>`.

After amending commits used in change requests, you can use `dfl write` to update the ephemeral branches.
If you packaged amendments in separate commits, you can use `dfl plan` to do add them to the existing change requests.

### Incorporating upstream changes

Once change requests are integrated into the upstream branch, you can update the local branch using `dfl pull`.
This invokes `git pull --rebase <remote> <upstream>` and prunes ephemeral branches if needed.
The same method can be used to pull in changes integrated into the upstream by others.

## How do I stack merge requests in Gitlab?

Suppose that you want to create three stacked merge requests out of three subsequent commits. Using `dfl plan`, create an [integration plan](#the-integration-plan) to create three stacked deltas.

```
d0 0 ...
d1@0 1 ...
d2@1 2 ...
```

This will create three ephemeral branches. Branch 0 containing commit 0, branch 1 containing commits 0 and 1, and branch 2 containing commits 0, 1, and 2.
Now push these ephemeral branches to Gitlab with `dfl push -m`.
The `-m` flag ensures that dflock uses git push options to create three merge requests: MR 0 to merge branch 0 into the upstream, MR 1 to merge branch 1 into branch 0, and MR 2 to merge branch 2 into branch 1.

Each merge requests will contain a clean diff containing only the changes of respectively commits 0, 1, and 2.

The merge requests should be merged in order. Once MR 0 is merged, Gitlab will automatically update the target branch of MR 1 to the upstream.

Gitlab [merge request dependencies](https://docs.gitlab.com/user/project/merge_requests/dependencies/#nested-dependencies), but dflock does not yet support automatically setting these dependencies.

You can [amend the change requests](#amending change requests) by updating the ephemeral branches and pushing them to Gitlab.

> [!CAUTION]
> If you push only some branches makes sure to also push downstream branches. Otherwise Gitlab will not display diffs correctly. For example, if you update MR 1 and push only that ephemeral branch, Gitlab will no longer recognize the commits in the target branch of MR 2 as being the same as the commits in MR 1 and will show a diff between branch 2 and the upstream (the last common ancestor of ephemeral branches 2 and 3).

## The integration plan

Integration plans play a central role in dflock. Typing `dfl plan` brings up a text editor showing the current integration plan. Each line of the plan consists corresponds to a commit and consists of a command, a truncated commit checksum, and the first line of the commit message.

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

To create Gitlab you have two options: By default, `dfl push` supports the `--merge-request` flag which will use [git push options](https://docs.gitlab.com/topics/git/commit/#push-options) to trigger merge-request creation when pushing to Gitlab.

Alternatively, you can add a custom integration, for example using the `glab` CLI. To do so, add the following to your [`.dflock` configuration](#configuration) file.

```
[integrations.gitlab]
change-request-template=glab mr create --source-branch {source} --target-branch {target}
```

To use this template in `dfl push`, invoke it with `--change-request github`.

### Github pull requests

For Github, you can create a custom change-request integration that uses the `gh` CLI tool. To do so, add the following to your `.dflock` configuration file.

```
[integrations.github]
change-request-template=gh pr create --head {source} --base {target}
```

To use this template in `dfl push`, invoke it with `--change-request github`.

## What commands does dflock support?

For a full list of commands, arguments, and options, use `dflock --help`. For information on each sub-command, use `dflock <sub-command> --help`.

### Plan

`dfl plan`

Detect and edit the current integration plan. This is operation automates the most complex parts of the workflow. It detects the integration plan from existing local branches and creates or updates ephemeral branches for change requests. Most other commands are essentially convenient shortcuts for common git commands.

### Write

`dfl write`

Detect the current integration plan and create or update the ephemeral branches accordingly. Normally `dfl plan` performs this operation, but `dfl write` is useful when the plan has not changed but you've amended or re-ordered commits in your local branch.

### Push

`dfl push`

Push ephemeral branches to the remote and optionally create change requests. You can also push branches selectively by adding their index shown in the output of `dfl status`. Instead of the index you can also type part of the ephemeral branch name as long as it uniquely indicates a branch.

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

`dfl checkout [BRANCH-NAME]`

Perform a `git checkout` on the local branch or an ephemeral branch if indicated. As a shortcut, the ephemeral-branch indices shown in the output of `dfl status` can be used here, or a substring of the branch name if it resolves to a unique branch.

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

### Github does not allow pull request dependencies

A Github pull request offers no way to block merging it before another pull request has been merged. Gitlab does support this, although dflock's default automatic merge request creation mechanism does not currently populate this field.

### Not pushing all deltas sometimes leads to incorrect diffs and conflicts

Consider the following plan:

```
d0 0 ...
d1@d0 1 ...
```

In our change requests we expect the diff of the first change request to show the changes in commit 0 and the diff of the second change request to show the changes in commit 1.

However, because dflock uses cherry-picking to create ephemeral branches, the SHAs of commits in ephemeral branches change each time the plan is written.

If, after writing the plan, we push only one of the two branches, the collaboration platform in might determine that the last common ancestor `d1` and `d0` no longer is commit 0, but the upstream and show the changes of both commit 0 and 1 in the diff of `d1`.

### Frequent updating of change requests

Because of [incorrect diffs when not pushing all deltas](#not-pushing-all-deltas-leads-to-incorrect-diffs), every time one change request in a series of stacked change requests is updated, all branches need to be pushed to the remote even though only one change request changed.

This might be undesirable if each update to a change request triggers notifications to reviewers or triggers a possibly expensive CI pipeline.

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

A request to integrate a set of commits (a delta) into the upstream. Gitlab and Github call this merge requests and pull requests respectively.

### Ephemeral branch

A branch containing a delta created by dflock for a change request. It's called ephemeral because it only serves to create a change request and dflock may delete the branch when it's no longer needed.
