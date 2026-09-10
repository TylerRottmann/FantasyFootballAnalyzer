# Fantasy Football Analyzer

A Django-based fantasy football analysis application.

## Table of Contents

* [Project Setup](#project-setup)
* [Git & GitHub Workflow](#git--github-workflow)

  * [Getting the Repository](#getting-the-repository)
  * [Branches](#branches)
  * [Creating a Feature Branch](#creating-a-feature-branch)
  * [Pull Requests](#pull-requests)
  * [Merging Dev into Main](#merging-dev-into-main)
  * [Git Commands Cheat Sheet](#git-commands-cheat-sheet)
* [Pull Request Requirements](#pull-request-requirements)
* [Project Management - Jira](#project-management---jira)
* [Sprint Workflow](#sprint-workflow)

---

# Project Setup

## 1. Clone the Repository

Clone the repository to your local machine:

```bash
git clone https://github.com/TylerRottmann/FantasyFootballAnalyzer.git
```

Navigate into the project (should do this automatically):

```bash
cd FantasyFootballAnalyzer
```

## 2. Run the Django Server

```bash
python manage.py runserver
```

The application should then be available at:

```text
http://127.0.0.1:8000/
```

---

# Git & GitHub Workflow

Our Git workflow uses three types of branches:

```text
main
  ↑
  │
 dev
  ↑
  │
feature/JIRA-TICKET
```

### `main`

`main` contains stable, sprint-approved code.

We **do not develop directly on `main`**.

### `dev`

`dev` contains the current development version of the application.

All completed feature branches are merged into `dev` through Pull Requests.

### Feature Branches

Feature branches are created from `dev` and are used for individual Jira tickets.

Every feature branch **must reference the Jira ticket it is completing**.

For example:

```text
feature/SCRUM-123-player-search
```

or:

```text
feature/SCRUM-456-player-ranking
```

The Jira ticket number should be included in the branch name.

---

# Getting the Repository

If you are a new contributor, clone the repository:

```bash
git clone https://github.com/TylerRottmann/FantasyFootballAnalyzer.git
```

Then enter the project directory:

```bash
cd FantasyFootballAnalyzer
```

Before beginning work, make sure you have the latest version of `dev`:

```bash
git checkout dev
git pull origin dev
```

You should **always create your feature branch from the latest version of `dev`**.

---

# Creating a Feature Branch

Do not make changes directly on `main` or `dev`.

Instead, start by updating your local `dev` branch:

```bash
git checkout dev
git pull origin dev
```

Then create a feature branch:

```bash
git checkout -b feature/SCRUM-123-player-search
```

Replace `SCRUM-123` with the Jira ticket you are working on.

You can verify which branch you are currently on with:

```bash
git branch
```

The branch with the `*` is your current branch.

---

# Working on a Feature

Make your changes on your feature branch.

When you are ready to commit:

```bash
git add .
git commit -m "Add player search"
```

Then push your feature branch to GitHub:

```bash
git push -u origin feature/SCRUM-123-player-search
```

After the first push, future changes can usually be pushed with:

```bash
git push
```

---

# Pull Requests

Once your Jira ticket is complete and your changes have been pushed to GitHub, create a Pull Request.

The Pull Request should be:

```text
feature/SCRUM-123-player-search → dev
```

Do **not** create feature Pull Requests directly into `main`.

Pull Requests allow the team to review changes before they become part of the development branch.

## Pull Request Description

Every Pull Request should include:

### 1. What Changed

Briefly explain what was implemented or fixed.

Example:

```text
Added a player search feature that allows users to search
for NFL players by name.
```

### 2. Files Changed or Added

List the important files that were modified or created.

Example:

```text
Added:
- analyzer/player_search.py

Modified:
- analyzer/views.py
- analyzer/urls.py
- analyzer/templates/home.html
```

### 3. UI Changes

If the Pull Request contains changes to the user interface, include screenshots showing the changes.

For example:

```text
Before:
[screenshot]

After:
[screenshot]
```

Screenshots are especially important for changes involving:

* Pages
* Forms
* Buttons
* Navigation
* Layout
* Styling
* Other visible UI changes

### 4. Jira Ticket

Reference the Jira ticket associated with the work.

Example:

```text
Jira: SCRUM-123
```

---

# Merging Dev into Main

At the end of each sprint, the team will review the current state of `dev`.

Once the sprint's work has been completed and reviewed, `dev` will be merged into `main`.

The process should be:

```text
Feature Branch
      │
      │ Pull Request
      ↓
     dev
      │
      │ End of Sprint
      │ Pull Request
      ↓
    main
```

The `main` branch should represent the stable version of the application at the completion of each sprint.

We should not merge unfinished feature work into `main`.

---

# Git Commands

The following commands are the most commonly used Git commands for this project.

## Checking Your Current Branch

See which branch you are currently working on:

```bash
git branch
```

The branch with the `*` is your current branch.

Example:

```text
* feature/SCRUM-123-player-search
  dev
  main
```

---

## Getting the Latest Changes

Update your current branch with the latest changes from GitHub:

```bash
git pull
```

To specifically update `dev`:

```bash
git checkout dev
git pull origin dev
```

It is recommended to pull the latest version of `dev` **before creating a new feature branch**.

---

## Switching Branches

Switch to an existing branch:

```bash
git checkout dev
```

or:

```bash
git checkout main
```

You can also use the newer syntax:

```bash
git switch dev
```

---

## Creating a New Feature Branch

Create and switch to a new branch:

```bash
git checkout -b feature/SCRUM-123-description
```

For example:

```bash
git checkout -b feature/SCRUM-123-player-search
```

Always create feature branches from the latest `dev` branch.

---

## Checking Your Changes

See which files have been modified, added, or deleted:

```bash
git status
```

---

## Staging Changes

Stage all changes:

```bash
git add .
```

Or stage a specific file:

```bash
git add path/to/file.py
```

---

## Committing Changes

Create a commit with a description of your changes:

```bash
git commit -m "Add player search"
```

Try to make commit messages concise and descriptive.

---

## Pushing Changes

Push your current branch to GitHub:

```bash
git push
```

For a newly created branch that has not been pushed before:

```bash
git push -u origin feature/SCRUM-123-player-search
```

After the first push, you can normally use:

```bash
git push
```

---

## Viewing Commit History

View previous commits:

```bash
git log
```

For a shorter version:

```bash
git log --oneline
```

---

## Viewing Branches

View local branches:

```bash
git branch
```

View local and remote branches:

```bash
git branch -a
```

---

## Updating Your Feature Branch With Dev

If `dev` has received changes while you were working on your feature, you may need to update your feature branch.

First update `dev`:

```bash
git checkout dev
git pull origin dev
```

Then switch back to your feature branch:

```bash
git checkout feature/SCRUM-123-description
```

Then merge the latest `dev` changes into your feature branch:

```bash
git merge dev
```

Resolve any merge conflicts if necessary, then commit and push the changes.

---

## Useful Workflow

A typical workflow for completing a Jira ticket is:

```bash
# Start from the latest dev
git checkout dev
git pull origin dev

# Create a feature branch
git checkout -b feature/SCRUM-123-description

# Make your changes...

# Check your changes
git status

# Stage your changes
git add .

# Commit your changes
git commit -m "Complete SCRUM-123"

# Push your feature branch
git push -u origin feature/SCRUM-123-description
```

Then create a Pull Request on GitHub:

```text
feature/SCRUM-123-description → dev
```

After the Pull Request is approved and merged, the Jira ticket is complete.

---

## Quick Reference

| Command                    | Purpose                                         |
| -------------------------- | ----------------------------------------------- |
| `git status`               | See the current state of your working directory |
| `git branch`               | See your local branches                         |
| `git checkout dev`         | Switch to `dev`                                 |
| `git checkout main`        | Switch to `main`                                |
| `git checkout -b <branch>` | Create and switch to a new branch               |
| `git pull`                 | Download and merge the latest changes           |
| `git add .`                | Stage all changes                               |
| `git commit -m "message"`  | Create a commit                                 |
| `git push`                 | Push commits to GitHub                          |
| `git log --oneline`        | View commit history                             |
| `git merge dev`            | Merge `dev` into your current branch            |


# Pull Request Requirements

Before creating a Pull Request, make sure:

* [ ] The branch was created from the latest `dev`
* [ ] The branch name references the Jira ticket
* [ ] The Jira ticket is complete or ready for review
* [ ] The code has been tested locally
* [ ] The project still runs correctly
* [ ] The Pull Request targets `dev`
* [ ] The Pull Request explains what changed
* [ ] The Pull Request lists important files that were added or modified
* [ ] Screenshots are included if there are UI changes
* [ ] The Jira ticket is referenced in the Pull Request

---

# Project Management - Jira

We use **Jira** to manage the project's development work.

Jira is used to organize:

* Features
* Bug fixes
* Improvements
* Development tasks
* Sprint work

Each piece of work should have its own Jira ticket.

Tickets are organized into **sprints**, with each sprint containing the work the team plans to complete during that sprint.

---

# Sprint Workflow

Our team will use weekly sprint grooming sessions to plan and organize upcoming work.

During sprint grooming:

1. The team reviews upcoming Jira tickets.
2. Tickets are discussed and clarified if necessary.
3. The team determines which tickets should be included in the upcoming sprint.
4. Tickets are assigned to team members.
5. Team members create feature branches for their assigned tickets.
6. Development takes place on the feature branches.
7. Completed work is submitted through Pull Requests into `dev`.
8. The team reviews and tests the changes.
9. At the end of the sprint, `dev` is merged into `main`.

### Example

Suppose Jira contains:

```text
SCRUM-101 - Create player search
SCRUM-102 - Add player rankings
SCRUM-103 - Create team comparison
```

During sprint grooming, these tickets might be assigned to different team members.

A developer assigned `SCRUM-101` would create:

```bash
git checkout dev
git pull origin dev
git checkout -b feature/SCRUM-101-player-search
```

After completing the work:

```bash
git add .
git commit -m "Add player search"
git push -u origin feature/SCRUM-101-player-search
```

They would then create a Pull Request:

```text
feature/SCRUM-101-player-search → dev
```

After review and approval, the feature is merged into `dev`.

At the end of the sprint, the team reviews the completed work and merges:

```text
dev → main
```

This keeps `main` stable while allowing the team to work independently on individual features.
