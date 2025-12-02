# Dflock

Dflock is a lightweight tool that automates the tedious parts of *diff stacking* on platforms that use branch-based *change requests* (pull requests in GitHub and merge requests in GitLab).

In a nutshell:

* dflock supports a workflow in which you commit all your work to a single branch;
* you periodically select which commits you want to submit for review to be integrated into the upstream;
* dflock creates the branches required to submit (stacked or independent) change requests for you.

Dflock aims to be minimalist: you interact with it via a CLI and by editing a **plain-text plan**, and dflock does not store any information apart from the branches it creates.

There's no need to convince your collaborators to change their workflows: dflock slots into conventional merge- or pull-request-based workflows on GitLab and GitHub.

You can use dflock to [create stacked merge requests in GitLab](#stacked-merge-requests-on-gitlab).
At the time of writing, GitHub pull requests behave in a way that makes [stacking them complicated](#stacked-pull-requests-on-github).

## Who is it for?

Developers who want to stack change requests, are comfortable editing Git history, and enjoy using text editors as a user interface.

## How do I install it?

Dflock is available on **PyPi**, so you can install it with pip.

```
pip install dflock
```

## What does it do?

Dflock's main specialty is creating Git branches for [change requests](#change-request) according to a plain-text [integration plan](#integration-plan).
This plan defines change requests and assigns commits to them.
If you indicate that there are dependencies between commits, dflock will create stacked change requests.
However, if you indicate that your commits can be integrated into the upstream in any order, dflock will create independent change requests.

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

The commits here are indicated by `c1`, `c2`, and `c3`, but normally the shortened commit hash would be shown.
The `s` directive tells dflock to skip the commit on that line, so the plan above doesn't do anything.
You can find more information about the integration plan syntax [here](#the-integration-plan).

> [!NOTE]
> The integration plan workflow and the plan's syntax are inspired by the workflow and syntax of the *interactive rebase* operation in Git.

To create change requests, we can edit the plan to look, for example, like this:

```git
d1 c1 Update README with overview of commands
d2 c2 Add functionality to update change requests to App class
d3@d2 c3 Add --update-change-request flag to push command
```

Here, `d1`, `d2`, and `d3@d2` are directives.
The `d` prefix tells dflock to create a change request.
A numeric label differentiates change requests.
The `@` symbol indicates a dependency and that the change request should be stacked on another.

The above plan assumes that commits `c1` and `c2` are independent, and that commit `c3` depends on the previous one.
Based on this plan, dflock will create three branches that we'll call `d1`, `d2`, and `d3` and cherry-pick the corresponding commits into them.
This creates the situation illustrated below.

```
origin/main ------> c0
                   / \
                  /\  c1
         d1 --> c1* \  \
         d2 ------> c2* c2
                      \  \
         d3 --------> c3* c3 <--- main
```

Cherry-picking will only be successfully if the changes in `c2` do not conflict with (i.e., change parts of files that were changed in) `c1`.

The created branches can be used to create three change requests: the target branch of `d1` and `d2` is the upstream, while `d3` targets `d2`. Note that GitHub uses the term *base branch* for what is referred to here as the target branch.

| Change request | Branch | Target branch |
| -------------- | ------ | ------------- |
| CR1            | d1     | main          |
| CR2            | d2     | main          |
| CR3            | d3     | d2            |

The change requests for `d1` and `d2` are independent and can be integrated in any order, but the change request for `d3` is stacked on `d2` and requires the change request for `d2` to be integrated first.

Dflock remembers the plan, even after more commits have been added or after some change requests have been integrated into the upstream branch.
This makes it easy to revisit the plan later---for example to add more commits to change requests or to create ones.

Dflock works well with a branchless workflow.
That workflow, and how to implement it using dflock, is described in the next section.

## Workflow and concepts

In the branchless workflow that works well with dflock, you commit all your work to a single branch referred to as the [*local*](#local) branch and never manually create branches.
The local branch tracks an [*upstream*](#upstream) branch, into which you aim to integrate your work via [*change requests*](#change-request).
Your local branch is usually a few commits ahead of the upstream.
These commits are your [*local commits*](#local-commits).
Your local commits are usually a mixture of work-in-progress and commits awaiting review and approval.

### Developing changes

You commit changes directly to the local branch.
There is no need to create branches for new features.
When you're done working on a feature, you simply keep committing to the same branch to work on further features.

### Submitting change requests

To create change requests, you periodically run `dfl plan` to bring up the [*integration plan*](#integration-plan).
Here you can selectively add commits to change requests and specify dependencies between the change requests.
Dflock calls a set of commits that have been added to a change request a [*delta*](#delta).

Based on the plan, dflock will create an [*ephemeral branch*](#ephemeral-branch) for each delta and cherry-pick the selected commits into them.
This process is triggered automatically when the plan is closed.
It can also be triggered manually using `dfl write`.

Dflock remembers your integration plan, so if you need to refine or edit it later, simply run `dfl plan` again to reopen it.

Ephemeral branches exist only to serve change requests.
All changes originate from commits to the local branch and flow via ephemeral branches and change requests into the upstream.
Dflock overwrites or prunes ephemeral branches regularly.
Therefore you generally should not commit to ephemeral branches directly.

When your deltas are ready to become change requests, run `dfl push` to push them to the remote. See the [setup for GitLab](#stacked-merge-requests-on-gitlab) or [GitHub](#stacked-pull-requests-on-github) for platform-specific notes on automatically creating change requests with dflock.

> [!NOTE]
> Note the local branch itself is never pushed to the remote in the above process.
> This is exactly what you want if your local branch the local copy of your upstream.
> However, you may just as well give a different name to your local branch.
> Doing so allows you to push your local branch to the remote and continue your work from a different machine.

### Amending change requests

If you want to change a published change requests, for example to address reviewer comments, you are free to use whatever method you prefer to re-order, amend, or drop local commits.
To facilitate this, dflock provides the command `dfl remix` to perform an interactive rebase on your local commits.
Under the hood, it invokes `git rebase --interactive <upstream>`.

After amending commits used in change requests, run `dfl write` to update the ephemeral branches.
If you've packaged your changes as separate commits, use `dfl plan` to do add them to the existing change requests.

Keep in mind that [dflock uses the commit messages of your local commits](#how-does-dflock-remember-plans) to remember the integration plan.

### Incorporating upstream changes

Once change requests are integrated into the upstream branch, update the local branch using `dfl pull`.
This command invokes `git pull --rebase <remote> <upstream>` and prunes ephemeral branches as needed.
You can use the same method to pull in changes that others have integrated into the upstream.

### Dealing with merge conflicts

Because your own change requests originate from a single branch, you cannot create merge conflicts between your own change requests.
Conflicts can arise only from changes made by collaborators.
To resolve these, rebase your local commits on the updated upstream (e.g., using `dfl pull`) and address any conflicts.
Then, run `dfl write` to recreate the ephemeral branches from the rebased local commits and push the conflicting branch again.

## How do I start using dflock?

By default, dflock uses `origin/main` as the upstream branch, `main` as the local branch (see [Workflow and concepts](#workflow-and-concepts) for an explanation of these concepts), and Nano as text editor.

You can override these defaults using configuration files:

* **Repository-specific overrides** can be stored in a file called `.dflock` in your repository's root folder.
* **Global configuration** can be stored in a `.dflock` file in your home folder.

You can interactively generate a repository-specific configuration file using `dfl init`.
The order of precedence for configuration options is: repository-specific, then global, then defaults.

These are the most important commands offered by dflock:

* `dfl plan` brings up the [integration plan](#integration-plan).
* `dfl status` shows current ephemeral branches.
* `dfl push` pushes all or a subset of ephemeral branches to the remote.
* `dfl log` displays your local commits.
* `dfl checkout` is convenient for checking out ephemeral branches.

Dflock can automatically create change requests when pushing branches.
See [this section](#automatic-merge-request-creation) for more information.

For a complete overview of available commands, use `dfl --help`.
For more information about a specific command, use `dflock <command> --help`.

## The integration plan

The integration plan plays a central role in dflock.
An example plan is shown below.

```
d c1 Update README with overview of commands
s c2 Add functionality to update change requests to App class
d3@d c3 Add --update-change-request flag to push command
```

Each line of the plan corresponds to a commit and is structured as follows: `<directive> <short commit hash> <first line of commit message>`.
The `s` directive tells dflock to skip that line.
Alternatively, the line can be [omitted entirely](#syntactical-rules).

If a directive starts with `d`  tells dflock to add the commit to a delta.
To distinguish between different deltas, a numeric label can be appended to the directive.
For example, `d0` and `d1` indicate different deltas.

The `@` symbol followed by a numeric label specifies dependencies between deltas.
For example, `d1@d0` creates a delta that depends on `d0`.

### Example plans

In the plans below commit checksums have been replaced by the numbers 0, 1, and 2, and commit messages which would be shown by `dfl plan` are omitted.

#### Selectively added commits

You can selectively add commits to a delta.

In the example below, only commit 1 is included in the delta, while commits 0 and 2 are skipped.

```
s 0 ...
d0 1 ...
s 2 ...
```


#### Multiple commits in one change request

You can also add multiple commits to a change request.

The plan below creates a single change request containing commit 1 and 2.

```
s 0 ...
d0 1 ...
d0 2 ...
```

#### Non-contiguous commits in one change request

Commits in a plan don't need to follow each other sequentially.

The plan below creates a single change request containing commit 0 and 2.

```
d0 0 ...
s 1 ...
d0 2 ...
```

#### Fully stacked change requests

You can create stacked change requests in which each change request contains one commit and depends on a change request containing the previous commit.
Dflock calls this type of plan *fully stacked*.

The example below shows a fully stacked plan.

```
d0 0 ...
d1@0 1 ...
d2@1 2 ...
```

#### Fully independent change requests

You can create independent change requests that can be integrated in an order different from the order of your local commits.

The plan below creates three fully independent change requests that can be integrated into the upstream branch in any order.

```
d0 0 ...
d1 1 ...
d2 2 ...
```

### Syntactical rules

Because plans are manually edited in a text editor, dflock supports several shortcuts that reduce amount of editing required to create unambiguous plans.

#### The `d` prefix can be omitted when referring to deltas after `@`

The directives `d1@d0` and `d1@0` are equivalent.

#### Skipping a commit is the same as deleting the entire line

You can simply remove lines containing commits you don't (yet) want to add to any delta.

For example, the two plans below are equivalent.

```
s 0 ...
d1 1 ...
```

```
d1 1 ...
```

#### Delta labels can be omitted

If a bare "d" is used as a directive, this serves as a distinguising label.

The following example shows how to create two different deltas using a bare "d" and "d0" directive.

```
d 0 ...
d0 1 ...
```

The above plan is equivalent to the plan below, which uses numeric labels and therefore requires a bit more writing.

```
d0 0 ...
d1 1 ...
```

You can refer to these deltas with "@" directives as follows:

```
d 0 ...
d0@d 1 ...
```

The same thing can be achieved with numeric labels and again a bit more typing as follows:

```
d0 0 ...
d1@d0 1 ...
```

#### Dependencies need to be specified only once

If you add multiple commits to a delta that has a dependency on another delta, you only need to specify that dependency once.

For example, the plan below adds two commits to `d1`, which depends on `d0`.
The dependency is indicated only on the final line which starts with `d1@d0`.

```
d0 0 ...
d1 1 ...
d1@d0 2 ...
```

## How does dflock remember plans?

Dflock does not actually store the plan anywhere, but it can reconstruct it by inspecting:

* commit messages of your local commits
* names of existing ephemeral branches (which are based on commit messages of local commits)

This works as long you don't manually change these or create local commits with duplicate messages.

If multiple commits are added to a delta, dflock by default uses the first commit to derive the branch name.
You can configure dflock to use the last commit instead by setting the `anchor-commit` configuration option to "last".

> [!NOTE]
> Because plans are reconstructed rather than saved, the reconstructed plans might show different numeric labels for your deltas.

## Constraints on plans

Dflock imposes constraints on what plans can be specified.
Some of these constraints aren't inherent to the workflow and might be lifted in future versions of dflock.

#### A delta cannot depend on multiple other deltas

It isn't possible to specify multiple dependencies for a delta.
For example, if you have three deltas: `d0`, `d1`, and `d2`, it isn't possible to make `d2` depend on both `d0` and `d1` if `d0` and `d1` are independent.

The only way around this is to make `d2` dependent on `d1` and `d1` dependent on `d0` as illustrated in the plan below.

```
d0 0 ...
d1@d0 1 ...
d2@d1 2 ...
```

#### Delta dependencies cannot cross

Once delta with a dependency occurs in a plan, all deltas following it must at least have the same dependency or depend on a delta following it.

For example, the following plan isn't allowed because `d1` depends on `d0`, and all change requests after `d1` must also depend on `d0` or change requests that came after it.

```
d0 0 ...
d1@d0 1 ...
d2 2 ...
```

In this particular situation, we can use `dfl remix` to re-order commits such that a valid plan can be constructed.
By swapping commits 2 and 1 we can construct the following valid plan:

```
d0 0 ...
d1 2 ...
d1@d0 1 ...
```

## Stacked merge requests on GitLab

GitLab has some features that facilitate stacking merge requests.
For example, if a merge request at the bottom of a stack is merged, Gitlab automatically changes the target branch of the next merge request to the upstream.
It is also possible configure [other merge requests as dependencies](https://docs.gitlab.com/user/project/merge_requests/dependencies/#nested-dependencies) of a merge request, preventing it from being merged into the upstream before its dependencies have been merged.

Here's an example illustrating the process.
Suppose that you want to create three stacked merge requests out of three subsequent commits.
To do this, use `dfl plan` to create an [integration plan](#the-integration-plan) and create three stacked deltas as shown below.

```
d1 c1 ...
d2@1 c2 ...
d3@2 c3 ...
```

To push these deltas to GitLab and create stacked merge requests automatically, run `dfl push -m` (see [automatic merge request creation](#automatic-merge-request-creation)).
The target branch of the merge request corresponding to `d1` will be the upstream, for `d2` it's `d1` and for `d3` it's `d2`.

When viewing these merge requests on Gitlab, their diffs will only show changes of their corresponding deltas.
That is, the diff of the merge request `d2` will show only changes in `c2` and that of `d3` only the changes in `c3`.

Because these merge requests are stacked, you should merge `d1` first.
After doing so, GitLab will update the merge request of `d2` to target the upstream instead of `d1`.
You can then merge `d2` and so on.

> [!NOTE]
> Make sure you select the checkbox for deleting the source branch in each merge request.
> This ensures that the target branch of the subsequently stacked merge request is updated correctly.

## Stacked pull requests on GitHub

You can use dflock with GitHub, but the experience of stacking pull requests is, at the time of writing, less smooth than with GitLab.
GitHub does not support pull request dependencies and merging the first pull request in a stack causes the next pull request in the stack to complain about merge conflicts.

## Automatic merge request creation

To automatically create merge requests with dflock in GitLab can use `dfl push` with the `--merge-request` flag.
This will trigger the creation of a merge request on GitLab using [Git push options](https://docs.gitlab.com/topics/git/commit/#push-options).

Alternatively, you can add a custom integration, for example using the `glab` CLI. To do so, add the following to your `.dflock` file.

```
[integrations.gitlab]
change-request-template=glab mr create --source-branch {source} --target-branch {target}
```

To use this integration run `dfl push` with the option `--change-request gitlab`.

## Automatic pull request creation

To automatically create pull requests on GitHub with dflock, you can for example add an integration that uses the `gh` CLI tool. To do so, add the following to your `.dflock` configuration file.

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

A request to integrate a *delta* into the *upstream*. GitLab calls this a **merge request** and GitHub calls this a **pull request**.

### Ephemeral branch

A branch created by dflock to support a *change request*. Depending on whether the change request is stacked, it contains one or mre *deltas*. It's called ephemeral because it only serves to create a change request and dflock may overwrite the branch or delete it when it's no longer needed.
