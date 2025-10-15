# Dflock

Dflock is a lightweight tool that automates the tedious parts of *diff stacking* on platforms that use branch-based *change requests* (pull requests in Github and merge requests in Gitlab).

In a nutshell:

* dflock supports a workflow in which you commit all your work to a single branch;
* you periodically select which commits you want to submit for review to be integrated in the upstream;
* dflock creates the branches required to submit (stacked or independent) change requests for you.

Dflock aims to be minimalist: you interact with it via a CLI and by editing a **plain-text plan** and dflock does not store any information apart from the branches it creates.

There's no need to convince your collaborators to change their workflows: dflock slots into conventional merge- or pull-request-based workflows on Gitlab and Github.

You can use dflock to [created stacked merge requests in Gitlab](#stacked-merge-requests-on-gitlab).
At the time of writing, Github pull requests behave in a way that makes [stacking them complicated](#stacked-pull-requests-on-github).

## Who is it for?

Developers who want to stack change requests, are comfortable editing git history, and are enthusiastic about using text editors as a user interface.

## How do I install it?

Dflock is on PyPi so you can install it with pip.

```
pip install dflock
```

## What does it do?

Dflock's main specialty is creating git branches for [change requests](#change-request) according to a plain-text [integration plan](#integration-plan).
This plan defines change requests and assigns commits to them.
If you indicate that there are dependencies between commits, dflock will create stacked change requests.
However, if you indicate that your commits can be integrated in the upstream in any order, dflock will create independent change requests.

For example, assume that your upstream branch is `origin/main` and that it points to commit `c0`.
On your local copy of `main`, you have three commits that have not been pushed yet.

```
                 ...
                 |
origin/main -->  c0  ...
                 |
                 c1  Update README with overview of commands
                 |
                 c2  Add functionality to update change requests to App class
                 |
       main -->  c3  Add --update-change-request flag to push command
```

At this point, you can edit the integration plan for these commits with dflock.
The initial plan created by dflock shows the three commits that exist on your local branch but not on the upstream.
It looks like this:

```git
s c1 Update README with overview of commands
s c2 Add functionality to update change requests to App class
s c3 Add --update-change-request flag to push command
```

The commits here are indicated by `c1`, `c2`, and `c3`, but normally the commit ID would be shown.
The `s` directive tells dflock to skip the commit on that line, so the plan above doesn't do anything.

Note that the integration plan looks a bit like the plan for an interactive rebase in git.
You can find more information about the integration plan syntax [here](#the-integration-plan).

To create change requests, we can edit the plan to look, for example, like this:

```git
d1 c1 Update README with overview of commands
d2 c2 Add functionality to update change requests to App class
d3@d2 c3 Add --update-change-request flag to push command
```

Here, `d1`, `d2`, and `d3@d2` are directives.
The `d` part tells dflock to create a change request.
It can be combined with the numeric label to differentiate change requests.
The `@` symbol indicates that the change request should be stacked on another change request.

The above plan assumes that commits `c1` and `c2` are independent, and that commit `c3` depends on the previous commit.
Based on this plan, dflock will create three branches that we'll call `d1`, `d2`, and `d3` and cherry pick the corresponding commits into them.
This creates the situation illustrated below.

```
origin/main ------> c0
                   / \
                  /\  \
                 /  \  c1
         d1 --> c1*  \  \
         d2 -------> c2* c2
                     |   |
         d3 -------> c3* c3 <--- main
```

Cherry picking will only be successfully the changes in `c2` do not conflict with (i.e., change parts of files that were changed in) `c1`.

The created branches can be used to create three change requests: change requests `d1` and `d2` have the upstream branch as they target branch, while `d3` has the `d2` as its target branch. Note that Github uses the term "base branch" for what I call target branch here.

```
 Change request | branch | target branch
----------------+--------+---------------
 CR1            | d1     | main
 CR2            | d2     | main
 CR3            | d3     | d2
```

The change requests for `d1` and `d2` are independent and can be integrated in any order, but the change request for `d3` is stacked on `d2` and requires the change request for `d2` to be integrated first.

Dflock remembers the plan, even after more commits have been added or after some change requests have been into the upstream branch.
This makes it easy to return to it later to, for example, add more commits to change requests or create new change requests.

Dflock works well with a branchless workflow.
For an overview of that workflow and how to use dflock with it, read on about the [workflow and concepts](#workflow-and-concepts).

## Workflow and concepts

In a branchless workflow you commit all your work to a single branch we'll call the [*local*](#local) branch.
This branch tracks an [*upstream*](#upstream) branch, into which you aspire to integrate your work via [*change requests*](#change-request).
Your local branch is usually a few commits ahead of the upstream.
These commits are your [*local commits*](#local-commits).
Your local commits are usually a mixture of work-in-progress and commits awaiting review and approval.

### Developing changes

You commit changes directly to the local branch. There is no need to create branches for new features. When one feature is finished and, you simply create more commits on the same branch to start working on the next one.

### Submitting change requests

To create change requests, you periodically run `dfl plan` to bring up the [*integration plan*](#integration-plan) in which you selectively assign sets of commits ([*deltas*](#delta)) to change requests and specify their inter-dependencies.
Based on the plan, dflock will create an [*ephemeral branch*](#ephemeral-branch) for each change request and cherry pick the selected commits into them.
Dflock remembers the integration plan. In case you need to refine or edit it, you can run `dfl plan` again to bring up the integration plan you previously created.

Importantly, ephemeral branches exist only to serve change requests.
You generally do not commit to or manipulate ephemeral branches directly because dflock overwrites them regularly and deletes them when they are no longer needed, for example after a change request has been integrated.

In other words, all changes originate from commits to the local branch and flow via ephemeral branches and change requests into the upstream.

When change requests are ready for submission, run `dfl push` to push them to the remote. See the [setup for Gitlab](#stacked-merge-requests-on-gitlab) or [Github](#stacked-pull-requests-on-github) for platform-specific notes on automatically creating change requests with dflock.


### Amending change requests

When making changes to published change requests, for example to address reviewer comments, you are free to use whatever method you prefer to re-order, amend or drop local commits.
To facilitate this, dflock provides the command `dfl remix` to perform an interactive rebase on your local commits.
Under the hood, it invokes `git rebase --interactive <upstream>`.

After amending commits used in change requests, run `dfl write` to update the ephemeral branches.
If you packaged amendments in separate commits, run `dfl plan` to do add them to the existing change requests.

Keep in mind that [dflock uses commit messages of local commits](#how-does-dflock-remember-plans) to remember the integration plan.

### Incorporating upstream changes

Once change requests are integrated into the upstream branch, update the local branch using `dfl pull`.
This invokes `git pull --rebase <remote> <upstream>` and prunes ephemeral branches if needed.
The same method can be used to pull in changes integrated into the upstream by others.

### Dealing with merge conflicts

Since your own change requests originate from a single branch, it is impossible to create merge conflicts with your own work.
The only way merge conflicts can arise is from changes made by collaborators.
This situation can be resolved by pulling in their changes (e.g., using `dfl pull`), running `dfl write` to update the ephemeral branches, and re-pushing the conficting branch.

## How do I start using dflock?

By default, dflock uses `origin/main` as the upstream branch, `main` as the local branch (see [workflow and concepts](#workflow-and-concepts) for and explanation of these concepts), and nano as text editor.

You can override these defaults using configuration files.
Repository-specific configuration can be stored in a file called `.dflock` in the repository's root folder.
You can interactively generate a repository-specific configuration file using `dfl init`.
Global configuration can be stored in a `.dflock` file in your home folder.
The order of precedence for configuration options is first repository-specific, then global, then defaults.

The most important commands are `dfl plan` to bring up the [integration plan](#integration-plan), `dfl status` to inspect ephemeral branches, `dfl push` to push all or a subset of ephemeral branches, `dfl log` to show your local commits, and `dfl checkout` to quickly checkout an ephemeral branch.

Dflock can create automatically change requests when pushing branches. See [this section](#automatic-merge-request-creation) for more information.

For a complete overview of available commands, use `dfl --help`.
For more information about a specific command, use `dflock <command> --help`.

## The integration plan

The integration plan plays a central role in dflock. Typing `dfl plan` brings up a text editor showing the current integration plan. Each line of the plan corresponds to a commit and consists of a command, a truncated commit checksum, and the first line of the commit message.

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

Since plans are edited in a text editor, there are some shortcuts that minimize the number of edits required for creating unambiguous plans.

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

## How does dflock remember plans?

Dflock uses commit messages of your local commits to derive the names of ephemeral branches.
As long as these don't change and as long as your local commits don't have duplicate messages, dflock should be able to reconstruct the plan.

If multiple commits are added to a delta, dflock by default uses the first commit to derive the branch name.
You can configure dflock to use the last commit instead by setting the `anchor-commit` configuration option to "last".

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

Gitlab has some features that facilitate stacking merge requests. For example, if a merge request at the bottom of a stack is merged, the target branch of the next merge request is updated automatically. It is also possible to assign [other merge requests as dependencies](https://docs.gitlab.com/user/project/merge_requests/dependencies/#nested-dependencies), which makes it impossible to merge before the dependencies have been merged.

Here's an example illustrating the process.
Suppose that you want to create three stacked merge requests out of three subsequent commits.
To do this, use `dfl plan` to create an [integration plan](#the-integration-plan) and create three stacked deltas as shown below.

```
d1 c1 ...
d2@1 c2 ...
d3@2 c3 ...
```

Then, to push these deltas to Gitlab and create stacked merge requests automatically, run `dfl push -m` (see [automatic merge request creation](#automatic-merge-request-creation)).
The target branch of the merge request corresponding to `d1` will be the upstream, for `d2` it's `d1` and for `d3` it's `d2`.

The diff of each merge request will show only the changes in its corresponding commit. That is, the diff of the merge request corresponding to `d2` will show only the changes in `c2` and that of `d3` only the changes in `c3`.

Because the merge requests are stacked, `d1` should be merged first (make sure to check the box for deleting the source branch).
After it has been merged, Gitlab will automatically update the target branch of the next merge request to the upstream. You can then merge `d2`, deleting its source branch, and so on.

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

To automatically create pull requests on Github with dflock, you can for example add an integration that uses the `gh` CLI tool. To do so, add the following to your `.dflock` configuration file.

```
[integrations.github]
change-request-template=gh pr create --head {source} --base {target}
```

To use this integration run `dfl push` with the option `--change-request github`.

## Why is it called dflock?

Dflock stands for *delta flock*. It is named as such because using the tool feels like herding a flock of deltas.

## Glossary

### Local

The local branch is where all development happens. It could be a local copy of the *upstream*, but it can also be a different branch. Using a local branch with a name than the upstream has the advantage that you can safely (force) push it to the remote.

### Upstream

The upstream is a remote branch into which you want to integrate commits on your local branch via *change requests*. The upstream is usually the main branch of the repository.

### Local commits

Commits on your *local branch* that do not exist in the *upstream branch*.

### Integration plan

A plain-text plan that instructs dflock which *deltas* to create, which commits they should contain, and how they depend on each other. See [this section](#the-integration-plan) for more information about integration plans.

### Delta

A set of changes that will be packaged in one *change requests*. A delta consists of one or more commits.

### Change request

A request to integrate a *delta* into the *upstream*. Gitlab calls this a **merge request** and Github calls this a **pull request**.

### Ephemeral branch

A branch created by dflock to support a *change request*. Depending on whether the change request is stacked, it contains one or mre *deltas*. It's called ephemeral because it only serves to create a change request and dflock may overwrite the branch or delete it when it's no longer needed.
