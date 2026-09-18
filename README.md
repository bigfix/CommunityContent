# BigFix Community Content Repository
See important notices regarding HCL Terms of Use at [TERMS](TERMS).  These terms are adapted from the original legal terms created for the original bigfix.me site, and may reflect some features (such as confidential areas and NDA agreements) that may not be relevant to this repository.

## Purpose

This repository is intended to foster sharing and collaboration between BigFix customers, partners, and enthusiasts.  This is a modernized replacement for the BigFix.Me site that has operated from October 2012 to the present day.  The purpose of this repository is to continue the legacy of BigFix.Me and carry forward the collaboration using the modern conveniences and standardized tooling supplied by github.

## Organization

The repository structure should follow standard BigFix Endpoint Manager (BES) Support Site Propagation conventions. Site content is organized as follows.

- **`Sites/<SiteName>Fixlets/`**: Stores content in standard BigFix `.bes` files.  Here 'Fixlets' is the broadest definition, where Fixlets include Fixlets, Tasks, Analyses.
- **`Sites/<SiteName>/Fixlets/Fixlets`**
- **`Sites/<SiteName>/Fixlets/Tasks`**
- **`Sites/<SiteName>/Fixlets/Analyses`**
- Additional top-level directories are optional, as are subdirectories beneath each of these.  For instance it would not be uncommon beneath a 'Windows' site to separate large numbers of fixlets by OS, for instance 'Fixlets/Fixlets/Win2019', 'Fixlets/Fixlets/Win2022', etc.

Each 'Site' *may* contain a 'site.xml' with relevance clauses or evaluation periods defined for the site.
Each directory beneath 'Fixlets' *may* contain a digest.xml with relevance clauses or evaluation periods that apply to all fixlets in that directory and child directories.

- **`Signatures`**: stores BigFix Inventory signatures.  Signature filenames should make clear the Product that is detected.  The Signatures directory may be further subdivided in the future.

An example directory structure may be illustrated as
```none
Sites/
├──BigFix Management
│   ├── Fixlets/
│   │   ├── Analyses/
│   │   │    └─ 13- Analysis1.bes
│   │   ├── Fixlets/
│   │   │    └─ 21- Fixlet1.bes
│   │   └── Tasks/
│   │        └─ 33- Task1.bes
├──Mac Software
│   ├── ...
└──Windows Software
    └── ...

Signatures/
├─react-server-dom CVE-2025-55182,AFFECTED.xml
└─react-server-dom CVE-2025-55182,SAFE.xml

```

## Attribution
For authorship attribution, please include frontmatter in the content (for example, XML comments or Markdown frontmatter) embedded in the content itself; and/or, MIME fields in .bes content, provided that such tags are schema-conformant and do not interfere with the ability to import/export such content into a BigFix deployment.  Check an existing Fixlet or Signature in this repo to see the format. While this frontmatter is optional, and it may be easier to exclude it when submitting custom content from your Console, if this frontmatter is present we use this to display your authorship in our Github Pages content browser.

## Content Validation Automation
This repository uses Github Actions to perform several validations on content that is submitted.  Some of those validations are extremely pedantic, possibly to the point of annoyance, so we ask for your patience as the rules are tuned.

If you regularly make contributions, we strongly encourage the use of the [pre-commit](https://pre-commit.com/) toolset.  pre-commit can automatically apply linting and symantec checks and automatically make corrections before your updates commit into the repo.  This repo includes a .pre-commit-config.yaml, the same used by our Github Actions to validate pull-requests, and includes default whitespace/YAML checks, a number of BigFix-specific content/ActionScript hooks courtesy of @jgstew, and a Trivy filesystem/config scan.

When submitting Pull Requests (see below), you may observe that several Github Actions run to validate your ssubmissions.  These validations are an aid to human review of your PR.  If any of the actions are marked with a Fail, it may be useful to review the action log and determine whether it is something that you can fix and resubmit (common issues include 'end-of-file-fixer' check, which expects a newline character at the end of the file; and 'trailing-whitespace', which gives an error if any line ends with unexpected spaces).  Some automatic fixes from pre-commit may not work in a Github Actions context (especially as your working branch may be a 'fork' into which our action cannot write); the curator team will review your submissions and determine whether we can merge, or ask you for changes before merging.

In addition to the syntax checks, all Fixlets/Tasks/Analyses and Inventory Signatures are validated against their reference XML schemas, and any newly-added `.bes` file must have a filename starting with a letter (see "Content Names" below).

Any pull request that touches something beneath `Sites/` is also scanned for download commands (`prefetch`, `add prefetch item`, `download`, `curl`, `wget`, etc.) inside each Fixlet/Task's ActionScript. If a download URL doesn't match one of the patterns in the repository's `known_urls.txt`, the pull request is labeled `new-download-url` and a maintainer is asked to confirm the URL before adding a matching pattern to `known_urls.txt`.

Separately, every download URL found this way is also submitted to [VirusTotal](https://www.virustotal.com/) for scanning; the pull request gets a comment summarizing the results (updated in place on later pushes, rather than piling up a new comment each time). If any scanner reports a URL as malicious, the pull request is additionally labeled `virustotal-flagged` and changes are requested.

Every push and pull request is also scanned for accidentally-committed secrets (via TruffleHog), and any change outside `Sites/*/Fixlets/` or the top-level `Signatures/` directory is flagged with the `needs-manual-review` label and requested changes, since it falls outside every automated check above and needs a maintainer's eyes.

## Pull Requests
This repository is meant for collaboration, and your submissions are critical to making this resource worthwhile.  We encourage you to use standard git concepts like branches, forks, and pull-request to submit content.  We do ask that we all try to maintain a reasonable Sites structure to divide content by areas of interest (such as 'BigFix Management', 'Windows Configuration', 'Linux Configuration', etc.).  We recognize that some content may be cross-platform and may not fit cleanly into these categories; we may create new categories in Sites and encourage you to do the same when necessary for clarity.

## Content Names
To allow for automated imports into a BigFix Root Server, each item of BigFix content (Fixlet/Task/Analysis) needs a unique ID.  For content in this repo, IDs are assigned automatically when we merge your submissions; your file is renamed with a numeric prefix and a hyphen.  To avoid conflicts with the automated number assignments, we ask that you start your filenames with alphabetic characters only - you may include numbers or symbols, but they should not be the first character of your filename.  Currently we use a simple auto-incrementing fixlet ID, but may switch to more deterministic ids in the future.

## Github Pages / Content Browser
This repository used Github Pages to provide an interactive content browser.  You may view this at our [Community Content Pages Site](https://bigfix.github.io/CommunityContent).  The Github Pages site allows fast searching, preview, direct downloads, and links to 'View on Github'.  We hope you find that interface useful, and welcome any feedback.  We especially welcome collaboration & updates, in the form of Pull Requests - the browser application is *itself* a part of this repository, primarily the 'index.html' at the root of this repo and the JavaScript loaded from 'docs/app.js'

## LEGAL AND LICENSE TERMS
Submissions migrated from https://bigfix.me are generally licensed under the terms of the [Creative Commons Attribute-ShareAlike 3.0 license](https://creativecommons.org/licenses/by-sa/3.0/legalcode.txt).  Modifications or submissions updated in this repository after the initial port are updated to the [Creative Commons Attribute-ShareAlike 4.0 license](https://creativecommons.org/licenses/by-sa/4.0/legalcode.txt) as defined at [LICENSE](LICENSE)
