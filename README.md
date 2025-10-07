# Dflock

Dflock is a git-complementing tool that automates the tedious parts of diff-stacking on platforms that use branch-based change requests (pull requests in Github and merge requests in Gitlab).

It enables a workflow in which all work happens on a single branch and commits are periodically and selectively added to change requests.

Dflock's main features are:

* Support for a [workflow](#workflow-and-concepts) in which you never create branches
* Helping you submit work as small incremental change requests
* Interaction and control via a text editor with [integration plans](#integration-plan)
* Simple and minimalist with a light footprint: the only state stored by dflock consists of git branches

You can use dflock together with git.
Dflock aims to complement git, not hide it.
Dflock slots into conventional merge- or pull-request-based workflows on Gitlab and Github.
Therefore, there is no need to convince all your collaborators to switch platforms or workflows before you can start using it.

You can [use dflock to created stacked merge requests in Gitlab](#stacked-merge-requests-on-gitlab).
At the time of writing, Github pull requests [behave in a way that makes stacking them complicated](#stacked-pull-requests-on-github).

## Who is it for?

Developers who want to stack change requests, are comfortable editing git history, and like the idea of using text editors as a user interface.

## What does it do?

Dflock's main specialty is to create git branches according to a text-based plan for change requests.
The plan defines change requests and assigns commits to them.
If there are dependencies between commits, the plan can be used to stack the corresponding change requests.
Sometimes, however, commits can be integrated independently.
This can be indicated in the plan too.

As an illustration, assume that your main branch points to commit `c0` and on top of that you have three commits that exist only on your own machine.
Dflock will show you the following integration plan.
Note that the plan looks a bit like the plan for an interactive rebase in git.

```git
s c1 Update README with overview of commands
s c2 Add functionality to update change requests to App class
s c3 Add --update-change-request flag to push command
```

The `s` directive tells dflock to skip the commit on that line, so the plan above doesn't do anything.

To create change requests, we can edit the plan to look, for example, like this:

```git
d1 c1 Update README with overview of commands
d2 c2 Add functionality to update change requests to App class
d3@d2 c3 Add --update-change-request flag to push command
```

The `d` directive combined with a numeric label tells dflock to create a change request and the `@` symbol is used for stacking change requests.
This plan assumes that commits `c1` and `c2` are independent, and that commit `c3` depends on the previous commit.
Based on the plan above, dflock will create three branches that we'll call `d1`, `d2`, and `d3` and cherry-pick commits into them as shown below.

```
main -->   c0
          / |
  d0 --> c1 c2 <-- d1
            |
            c3 <-- d2
```

The cherry-picking will only be successfully the changes in `c2` do not conflict with (i.e., change parts of files that were changed in) `c1`.

The created branches can be used to create three change requests: change requests `d1` and `d2` have the upstream branch as they target branch, while `d3` has the `d2` as its target branch. Note that Github uses the term "base branch" for what I call target branch here.

Note that `d1` and `d2` can be integrated in any order, but `d3` requires `d2` to be integrated first.

Dflock remembers the plan, even after more commits are added or if its change requests have been partially integrated into the main branch.
This makes it easy to return to it later to, for example, add more commits to change requests or create new change requests.

## How do I install it?

Dflock is on PyPi so you can install it with pip.

```
pip install dflock
```

## How do I use it?

First, determine which branches you want to use as your [upstream](#upstream) and [local](#local) (read more about these concepts [here](#workflow-and-concepts)).

By default, dflock assumes `origin/main` as the upstream and `main` as the local.

To change this and to set some other configuration options such as the text editor to use for plans, use `dfl init` to interactively generate a configuration file.

The configuration is stored in your repository's root folder in a file called `.dflock`. You can edit it later if you change your mind about some of the settings.
If you want to re-use configuration across projects, move `.dflock` to `~/.dflock`.

Having committed some work to your local branch, create one or more change requests using `dfl plan`.
This brings up the [integration plan](#integration-plan).

If the plan executes successfully, you inspect the created branches with `dfl status`.

To push the branches to the remote, use `dfl push`.

You can also selectively push branches using their index in the output `dfl status`. For example, to push only the first branch, use `dfl push 0`.

Dflock can create change requests automatically while pushing branches to some platforms. See [this section](#automatic-merge-request-creation) for more information.

Otherwise, you can use the pushed branches to create change requests manually. To see an overview of branches and target branches created by dflock, use
`dfl status --show-targets`.

These steps illustrate only basic usage. For a complete overview of available commands, use `dfl --help`. For more information about a specific command, use `dflock <command> --help`.

## Workflow and concepts

Dflock is built for a workflow in which almost all work is done in a single branch, called the [*local*](#local) branch.
This branch tracks an [*upstream*](#upstream) branch, into which your work aspires to be integrated via [*change requests*](#change-request).
Your local branch is usually a few commits ahead of the upstream.
These commits are your [*local commits*](#local-commits).
Your local commits are usually a mixture of work-in-progress and commits awaiting review and approval.

### Development of changes

You commit changes directly to the local branch. There is no need to create branches for new features. When one feature is finished and, you simply create more commits on the same branch to start working on the next one.

### Submitting change requests

To create change requests, you periodically run `dfl plan` to bring up the [*integration plan*](#integration-plan) in which you selectively assign sets of commits ([*deltas*](#delta)) to change requests and specify their inter-dependencies.
Based on the plan, dflock will create an [*ephemeral branch*](#ephemeral-branch) for each change request and cherry-pick the selected commits into them.
Dflock remembers the integration plan. In case you need to refine or edit it, you can run `dfl plan` again to bring up the integration plan you previously created.

Importantly, ephemeral branches exist only to serve change requests.
You generally do not commit to or manipulate ephemeral branches directly because dflock cleans up these branches when they are no longer needed.
This happens for example after the change request has been integrated.
All changes originate from the local branch, flowing via ephemeral branches into the remote upstream.

When the change requests are ready for submission, run `dfl push` to push them to the remote. See the [setup for Gitlab](#stacked-merge-requests-on-gitlab) or [Github](#stacked-pull-requests-on-github) for platform-specific notes on automatically creating change requests with dflock.

### Amending change requests

When making changes to published change requests, for example to address reviewer comments, you are free to use whatever method you prefer to re-order, amend or drop local commits.
To this end, dflock provides the command `dfl remix`, which invokes `git rebase --interactive <upstream>`.

After amending commits used in change requests, run `dfl write` to update the ephemeral branches.
If you packaged amendments in separate commits, run `dfl plan` to do add them to the existing change requests.

### Incorporating upstream changes

Once change requests are integrated into the upstream branch, update the local branch using `dfl pull`.
This invokes `git pull --rebase <remote> <upstream>` and prunes ephemeral branches if needed.
The same method can be used to pull in changes integrated into the upstream by others.

## The integration plan

The Integration plan plays a central role in dflock. Typing `dfl plan` brings up a text editor showing the current integration plan. Each line of the plan corresponds to a commit and consists of a command, a truncated commit checksum, and the first line of the commit message.

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

#### Multiple commits in one change request

This plan creates a single change request containing commit 1 and 2.

```
s 0 ...
d0 1 ...
d0 2 ...
```

#### Non-contiguous commits in one change request

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

Since plans are edited in a text editor, the syntax includes support for shortcuts that minimize the number of edits required for creating unambiguous plans.

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

#### Delta labels can be omitted

An omitted label serves as a distinguishing label.

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
d1@d 1 ...
```

is the same as

```
d0 0 ...
d1@d0 1 ...
```

#### In change requests with multiple commits, specifying the target-branch once is enough

```
d0 0 ...
d1 1 ...
d1@d0 2 ...
```

is the same as

```
d0 0 ...
d1@d0 1 ...
d1@d0 2 ...
```

## Constraints on plans

Dflock imposes some constraints on what plans can be specified. These constraints are not inherent to the workflow and might be lifted in future versions of dflock.

#### A change request cannot depend on multiple change requests

The only way to make d2 depend on both d0 and d1 is to fully stack them:

```
d0 0 ...
d1@d0 1 ...
d2@d1 2 ...
```

#### Change request dependencies can not cross

The following is not allowed:

```
d0 0 ...
d1@d0 1 ...
d2 2 ...
```

because `d1` depends on `d0`, and all change requests after `d1` must also depend on `d0` or change requests that came after it.
Note that a change request with no specified dependency has an implicit dependency on the upstream.

In this particular situation we can use `dfl remix` to re-order the commits such that a valid plan can be constructed.
If we swap commit 2 with commit 1, we can construct the following valid plan:

```
d0 0 ...
d1 2 ...
d1@d0 1 ...
```

## Stacked merge requests on Gitlab

Gitlab to some extend faciliates stacked merge requests. For example, if a merge request at the bottom of the stack is merged, the target branch of the next merge request is updated automatically.

The steps below outline, using a simple example, how to stack merge requests.

Suppose that you want to create three stacked merge requests out of three subsequent commits. To do this, first use `dfl plan`, create an [integration plan](#the-integration-plan) as shown below to create three stacked deltas.

```
d1 c1 ...
d2@1 c2 ...
d3@2 c3 ...
```

Then, to push these deltas to Gitlab and create stacked merge requests automatically, run `dfl push -m` (see [automatic merge request creation](#automatic-merge-request-creation)).
The target branch of the merge request corresponding to `d1` will be the upstream, for `d2` it's `d1` and for `d3` it's `d2`.

The diff of each merge request will show only the changes in its corresponding commit. That is, the diff of the merge request corresponding to `d2` will show only the changes in `c2` and that of `d3` only the changes in `c3`.

The merge requests should be merged in order. Once the merge request of `d1` has been merged (make sure to delete the source branch), Gitlab will automatically update the target branch of the next merge request to the upstream.

If you have any merge conflicts, be sure to solve the by rebasing your local branch on the upstream (e.g., using `dfl pull`).

Gitlab supports [merge request dependencies](https://docs.gitlab.com/user/project/merge_requests/dependencies/#nested-dependencies) which prevent a merge before its dependencies have been merged.
This is ideal for stacked merge requests, but dflock does not yet support automatically setting these dependencies.

## Stacked pull requests on Github

You can use dflock with Github, but the experience of stacking pull requests is, at the time of writing, less smooth than with Gitlab: Github does not support pull request dependencies and merging the first pull request in a stack causes the next pull request in the stack to complain about merge conflicts.

## Automatic merge request creation

To automatically create merge requests with dflock in Gitlab can use `dfl push` with the `--merge-request` flag.
This will trigger the creation of a merge request on gitlab using [git push options](https://docs.gitlab.com/topics/git/commit/#push-options).

Alternatively, you can add a custom integration, for example using the `glab` CLI. To do so, add the following to your `.dflock` file.

```
[integrations.gitlab]
change-request-template=glab mr create --source-branch {source} --target-branch {target}
```

To use this integration run `dfl push` with the option `--change-request gitlab`.

## Automatic pull request creation

To automatically create pull requests on Github with dflock, you have to add an integration that uses the `gh` CLI tool. To do so, add the following to your `.dflock` configuration file.

```
[integrations.github]
change-request-template=gh pr create --head {source} --base {target}
```

To use this integration run `dfl push` with the option `--change-request github`.

## Why is it called dflock?

The name dflock derives from *delta flock*, because the tool allows you to herd a flock of deltas.

## Glossary

### Local

The branch used for development. This could be a personal branch called `<your-name>-WIP` (which is safe to force-push to the remote) or it could be your local copy of `main` (which should obviously not be pushed to the remote).

### Upstream

The remote branch into which commits on your local branch aspire to eventually be integrated. Often the main branch of the repository.

### Local commits

Commits you are working on that are only on your local branch and not in the upstream. More precisely: commits reachable from the local branch, but not from upstream branch.

### Integration plan

A text-based representation of a tree-like structure that instructs dflock which deltas to construct and how they depend on each other. See [this section](#the-integration-plan) for more information about integration plans.

### Delta

A set of changes represented by one or more commits.

### Change request

A request to integrate a set of commits (a delta) into the upstream. Gitlab and Github call this merge requests and pull requests respectively.

### Ephemeral branch

A branch containing a delta created by dflock for a change request. It's called ephemeral because it only serves to create a change request and dflock may delete the branch when it's no longer needed.
