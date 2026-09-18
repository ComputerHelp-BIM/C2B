# CAD files in this repository (Git LFS)

Every `.dxf`, `.dwg`, `.rvt`, `.rfa` and `.rte` in this repository is stored with **Git LFS**.
The commit carries a sixty-byte pointer; the file itself lives on GitHub's LFS server and is
fetched when you check it out.

You mostly do not have to think about it. `git clone`, `git pull` and `git push` all work the
way they normally do — **once Git LFS is installed on the machine.** Install it before your
first clone and nothing else on this page will ever matter to you.

---

## 1. Install it — once per machine

**Windows.** Git for Windows ships with Git LFS, so it is usually already there. Check:

```bat
git lfs version
```

If that prints a version, skip to the next step. If it says `'lfs' is not a git command`:

```bat
winget install GitHub.GitLFS
```

or download the installer from [git-lfs.com](https://git-lfs.com) and run it.

**macOS:** `brew install git-lfs`  **Ubuntu/Debian:** `sudo apt install git-lfs`

**Then, once, on every machine:**

```bat
git lfs install
```

That adds the hooks that swap pointers for real files. It is per user account, not per
repository — you run it once and forget it.

---

## 2. Clone

Nothing special:

```bat
git clone https://github.com/ComputerHelp-BIM/C2B.git
cd C2B
```

If Git LFS was installed first, the drawings arrive whole. Check one:

```bat
git lfs ls-files
```

It should list the DXFs. `samples\Test10.dxf` should be about **3.7 MB**, not 130 bytes.

> **If you cloned before installing Git LFS**, every CAD file is a short text file starting
> `version https://git-lfs.github.com/spec/v1`. You do not need to clone again:
>
> ```bat
> git lfs install
> git lfs pull
> ```

**Cloning without the drawings.** If you only want the code — a build machine, a quick look —
skip the downloads:

```bat
git clone --filter=blob:none https://github.com/ComputerHelp-BIM/C2B.git
```

or set `GIT_LFS_SKIP_SMUDGE=1` before cloning. `git lfs pull` fetches them later when you want
them.

---

## 3. Fetch and pull

Exactly as usual:

```bat
git pull origin claude/adoring-sagan-2h8b4x
```

Pull brings down the LFS files for whatever it checks out. To force a fetch of the drawings
alone — after a network failure, or after skipping them at clone time:

```bat
git lfs pull
```

`git lfs fetch --all` gets every version of every file, which you want only when taking a
backup.

---

## 4. Push

Exactly as usual:

```bat
git add .
git commit -m "..."
git push -u origin claude/adoring-sagan-2h8b4x
```

Git LFS uploads the file contents **before** the branch moves, so a failed upload aborts the
push and leaves the server untouched. You will never end up with a pointer on GitHub that has
no file behind it.

A push shows the upload:

```text
Uploading LFS objects: 100% (7/7), 36 MB | 0 B/s, done.
```

---

## 5. Adding a new drawing

Put the file in `samples\` or `templates\` and commit it. `.gitattributes` already says which
extensions go to LFS, so nothing else is needed:

```bat
copy "C:\jobs\TowerB.dxf" samples\
git add samples\TowerB.dxf
git commit -m "Add Tower B for testing"
git push
```

Confirm it went to LFS rather than into the history itself:

```bat
git lfs ls-files
```

If a new file type needs the same treatment, add it to `.gitattributes` and commit that:

```bat
git lfs track "*.ifc"
git add .gitattributes
```

---

## 6. What is in here, and what it costs

| | |
| --- | --- |
| CAD files tracked | `*.dxf` `*.dwg` `*.rvt` `*.rfa` `*.rte`, plus `*.rar` `*.zip` |
| In LFS today | about 36 MB across 7 files |
| GitHub's free allowance | 1 GB of LFS storage and 1 GB of transfer a month — check **Settings → Billing** for where you actually stand |

A fresh clone spends about 36 MB of that monthly transfer, so roughly twenty-five full clones a
month before it matters. If CI ever clones this repository on every run, give it
`GIT_LFS_SKIP_SMUDGE=1` — it does not need the drawings to run the tests.

### Why bother

A DXF is text, so git *can* store it. The problem is the next version of it. A structural
drawing is tens of megabytes and an edit rewrites most of the file, so git cannot pack
successive versions against each other: every revision adds its whole self to the history, and
stays there for everyone, forever. With LFS a revision costs a pointer, and a clone fetches
only the versions it actually checks out.

### The files committed before this

The drawings were committed normally before being moved to LFS, so those blobs are still in
this branch's history. Packed they come to about **4 MB in total** — DXF is repetitive text and
compresses roughly ten to one — so rewriting the branch to remove them would save less than it
would cost everyone holding a clone. They stay. From here on every revision is a pointer.

---

## 7. When something looks wrong

| Symptom | What it is | Fix |
| --- | --- | --- |
| A DXF is ~130 bytes and starts `version https://git-lfs.github.com/spec/v1` | LFS was not installed when it was checked out | `git lfs install` then `git lfs pull` |
| `git lfs ls-files` prints nothing | This clone has no LFS files checked out, or LFS is not installed | `git lfs version`, then `git lfs pull` |
| A push hangs on *Uploading LFS objects* | A slow or blocked connection to the LFS endpoint | Retry; a failed upload aborts the push without touching the server |
| `batch response: This repository is over its data quota` | The LFS allowance is spent | Buy a data pack, or trim old versions with `git lfs prune` on the server side |
| AutoCAD says a drawing is corrupt | It is a pointer file, not a drawing | As the first row |

`git lfs status` says what is staged and whether it is going to LFS. `git lfs env` prints the
endpoint being used, which is the first thing to look at if pushes fail.
