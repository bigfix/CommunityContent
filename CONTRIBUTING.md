# As-Is

All content is submitted, as-is and not supported and/or maintained by HCLSoftware

# Contributing

Thank you for contributing to this repository. This project preserves and continues the community content previously hosted at bigfix.me. Please read this file before submitting a pull request ("PR").

# License of your contribution

By submitting a PR to this repository, you agree that your contribution is licensed to the public under the [Creative Commons Attribution-ShareAlike 4.0 International License (CC BY-SA 4.0)](https://creativecommons.org/licenses/by-sa/4.0/legalcode.txt), unless your PR modifies content that was migrated from bigfix.me, in which case see "Contributions that build on migrated content" below.

This means, among other things, that:

- Anyone may reuse, adapt, and redistribute your contribution, provided they give you (or your designated attribution name) credit and license their own adaptations under CC BY-SA 4.0 or a compatible license.
    
- You are not granting any patent rights, and you are not required to grant HCL any rights beyond what CC BY-SA 4.0 itself provides.
    

# Contributions that build on migrated content

Some files in this repository were migrated from bigfix.me and remain licensed under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/legalcode.txt) (see the file header or the NOTICE file for the original contributor's attribution). If your PR modifies one of these files:

- The unmodified portions remain under CC BY-SA 3.0, and the original attribution notice must be kept intact.
    
- Your own modifications may be released under CC BY-SA 4.0, since 3.0 permits adaptations to be shared under a later version with the same license elements (Attribution, ShareAlike).
    
- Please note in your PR description, and in a comment or header in the file, that the contribution is an adaptation of migrated bigfix.me content, and identify what you changed.
    

# Representations you are making

By submitting a PR, you represent and warrant that:

1. You own the content you are contributing, or you have obtained all rights, releases, and authorizations necessary to submit it and license it as described above.
    
2. To the best of your knowledge, your contribution does not infringe any copyright, patent, trade secret, or other intellectual property or proprietary right of any third party.
    
3. Your contribution does not contain any malware, viruses, or other harmful code.
    
4. Your contribution does not contain any confidential or trade secret information belonging to you or any third party.
    
5. You are legally entitled to grant the license described above, whether on your own behalf or on behalf of your employer (if your employer has rights to intellectual property you create).
    

If any of the above is not true, please do not submit the PR — contact the maintainers first.

# Attribution

Please add or confirm an attribution name (your GitHub username, or another name/pseudonym you'd like credited) in your PR. Attribution for contributions migrated from bigfix.me will use the contributor's original bigfix.me username, per the terms under which that content was originally submitted.

# No warranty; no obligation to merge

Content in this repository is provided "as is," without warranty of any kind — see the repository LICENSE and README for the full disclaimer that applies to anyone using or downloading this content. Maintainers may decline, edit, or remove any contribution at their discretion, and are under no obligation to merge, support, or maintain any particular contribution.

# Questions

If you're unsure whether you can agree to the above — for example, because your contribution is based on someone else's work, or was created in the course of employment — please reach out to the maintainers before submitting a PR.

# How to Contribute: Fork and Pull Request Walkthrough

This is a step-by-step template for making a contribution using GitHub's fork-and-pull-request workflow. If you're already comfortable with Git and GitHub, feel free to skim - the sections above are the parts that actually matter (license, representations, attribution); this section is just the "how."

## 1. Fork the repository

1. On this repository's GitHub page, click **Fork** (top right) to create your own copy under your GitHub account.
2. Clone your fork locally:

    ```bash
    git clone https://github.com/<your-username>/CommunityContent.git
    cd CommunityContent
    ```

3. Add the original repository as a remote named `upstream`, so you can pull in future updates:

    ```bash
    git remote add upstream https://github.com/bigfix/CommunityContent.git
    ```

## 2. Create a branch

Create a new branch off the latest `main` for your contribution, with a short, descriptive name:

```bash
git checkout main
git pull upstream main
git checkout -b add-<short-description>
```

## 3. Add or edit content

- Place new Fixlets, Tasks, and Analyses under `Sites/<SiteName>/Fixlets/` (see "Organization" in the README for the full structure and an example layout).
- Place new Inventory Signatures directly under `Signatures/`.
- Start new filenames with a letter, not a number (see "Content Names" in the README) - numeric prefixes are reserved for auto-assigned content IDs.
- Where you can, include attribution frontmatter/MIME fields in your content (see "Attribution" above).
- If you're modifying content migrated from bigfix.me, note that in both the file and your PR description (see "Contributions that build on migrated content" above).

If you have [pre-commit](https://pre-commit.com/) installed, run it locally before committing - it catches and fixes many of the same issues our GitHub Actions check for:

```bash
pre-commit run --all-files
```

## 4. Commit and push

Write a clear, specific commit message describing what you added or changed:

```bash
git add <path/to/your/files>
git commit -m "Add <SiteName>: <short description of the Fixlet/Task/Analysis>"
git push origin add-<short-description>
```

## 5. Open a pull request

1. On GitHub, navigate to your fork; you should see a prompt to open a pull request from your new branch.
2. Target this repository's `main` branch.
3. In the PR description:
    - Briefly describe what you're contributing and why.
    - Confirm (or provide) your attribution name (see "Attribution" above).
    - Note if your contribution builds on migrated bigfix.me content.
    - Opening the PR confirms you agree to the terms above (see "License of your contribution" and "Representations you are making").

## 6. Respond to automated checks and review

- GitHub Actions will automatically validate your submission (schema checks, filename rules, download-URL checks, and more - see "Content Validation Automation" in the README). Some checks are pedantic; review the failing check's log for the specific reason, then push a fix to the same branch to re-trigger validation.
- Some checks, such as using a new download URL, will require approval from a curator.  No worries, your submission will be reviewed even if some of the checks fail.
- A maintainer will review your PR, may ask questions or request changes, and will merge it once everything looks good. There's no guaranteed timeline, and maintainers are under no obligation to merge any particular contribution (see "No warranty; no obligation to merge" above).

## 7. Keeping your fork up to date (for future contributions)

```bash
git checkout main
git pull upstream main
git push origin main
```
