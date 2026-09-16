# github_pages_fixlet_browser

Code related to establishing a Fixlet Browser in Github Pages

Content (`.bes` Fixlets/Tasks/Analyses/Baselines, and BigFix Inventory `Signatures/*.xml`) is published as static files by publishing the whole repo root as the Pages site - the browser fetches each file directly from `Sites/` / `Signatures/`, with no duplicate copy kept anywhere. The browser app never calls the GitHub API or fetches from the source repo to show or download a file - the only link back to GitHub is the explicit "View on GitHub" link. See CLAUDE.md for the full architecture writeup.

## Setup

Copy the content from this repo (`index.html`, `pages/`, `.github/workflows/update-index.yml`) into the repository containing the BigFix content.
Put/edit your `.bes` files under `Sites/<SiteName>/Fixlets/` at the repo root (any subdirectory depth beneath `Fixlets/` is picked up), and any BigFix Inventory Signature files under `Signatures/` at the repo root.
Enable Github Actions on the repo, with "Read and Write Permissions".
Enable Github Pages on the repo, with "Deploy from a branch" set to `main` / `/ (root)`.
Update `pages/config.json` (`defaultOwner`, `defaultRepo`, `defaultBranch`, `githubSite`) to match the repo you're deploying into - these only affect the "View on GitHub" link, not content retrieval.
Execute the Github Action, or run `python pages/generate_index.py` locally from the repo root and commit the result, to build the initial `pages/index.json`.
Browse to the Github Pages site for this repo.

`/Sites`, `/Signatures`: canonical source of `.bes` and Signature `.xml` files. Edit/add/remove files here to change what the browser shows - they're served as-is, with no copy step.

`/index.html`: Github Pages entry point (published from the repo root), referencing `pages/app.js`, `pages/style.css`, and `pages/index.json`.

`/pages`: supporting assets for the viewer.

* `app.js` reads `pages/index.json` to provide a list of Fixlets/Tasks/Analyses/Baselines/Signatures to the browse interface.
* When one is selected, the content is fetched directly from `Sites/`/`Signatures/` (served at the Pages site root) - not from GitHub.
* `config.json` holds the owner/repo/branch/GitHub-host defaults used only for the "View on GitHub" link (see Setup above).
* `generate_index.py` is the index-generation script (see below).

`/pages/generate_index.py`: index-generation script

* Enumerates `.bes` files under `/Sites` and Signature files under `/Signatures`.
* Generates `pages/index.json` containing metadata for the files read by the Github Pages User Interface. Does not copy or duplicate any file.

`/.github/workflows/update-index.yml`: Github Action definition to update the index

* Executes `pages/generate_index.py` on every push to `main` that touches `Sites/**` or `Signatures/**`, so `pages/index.json` stays in sync with `/Sites` and `/Signatures`.
