# BigFix Community Content Repository
See important notices regarding HCL Terms of Use at [TERMS](TERMS).  These terms are adapted from the original legal terms created for the original bigfix.me site, and may reflect some features (such as confidential areas and NDA agreements) that may not be relevant to this repository.

## Purpose

This repository is intended to foster sharing and collaboration between BigFix customers, partners, and enthusiasts.  This is a modernized replacement for the BigFix.Me site that has operated from October 2012 to the present day.  The purpose of this repository is to continue the legacy of BigFix.Me and carry forward the collaboration using the modern conveniences and standardized tooling supplied by github.

## Organization

Content in this repo should be organized in directory structures mirroring what one might expect from Custom Sites organization in a BigFix Deployment (which provides for ease of direct copies into a BigFix Deployment).  BigFix Platform content - Fixlets, Analyses, Tasks, ComputerGroups, etc. - should be submitted as .bes files for direct import to the Console; BigFix Inventory Signatures should be submitted as .xml files that can be directly uploaded or pasted into the BigFix Inventory interface; AI skills should be submitted as Markdown documents.

While this certainly may change over time, an example expected structure may be represented as
```
/Content/BigFix Management/Task/Relay - Apply _BESClient_Relay_NameOverride.bes
/Content/BigFix Management/Task/Relay - Remove _BESClient_Relay_NameOverride.bes
/Content/BigFix Management/Analysis/Relay Properties.bes
/Content/BigFix Management/Fixlet/BES Server - Apply directory exclusions for Defender scans - Windows.bes
/Content/BigFix Management/Fixlet/BES Server - Remove directory exclusions for Defender scans - Windows.bes

/Content/Windows Software/Task/Notepad++ - Install.bes
/Content/Windows Software/Task/Notepad++ - UnInstall.bes
/Content/Windows Software/Fixlet/Notepad++ - Upgrade.bes
/Content/Windows Software/Analysis/Install Sofware List - Windows.bes

/Content/Mac Software/Task/VSCode - Install.bes
/Content/Mac Software/Task/VSCode - UnInstall.bes
/Content/Mac Software/Fixlet/VSCode - Upgrade.bes

/Content/BigFix Inventory Signatures/react-server-dom CVE-2025-55182,AFFECTED.xml
/Content/BigFix Inventory Signatures/react-server-dom CVE-2025-55182,SAFE.xml

/Content/AI Skills/Relevance-Generator-Skill.md
/Content/AI Skills/Product-Release-Detector-Skill.md
/Content/AI Skills/Fixlet-Generator-Skill.md
/Content/AI Skills/BigFix-Operator-Skill.md
```

## Attribution
For authorship attribution, if desired please include frontmatter in the content (for example, XML comments or Markdown frontmatter) embedded in the content itself; and/or, MIME fields in .bes content, provided that such tags are schema-conformant and do not interfere with the ability to import/export such content into a BigFix deployment.


## LEGAL AND LICENSE TERMS
Submissions migrated from https://bigfix.me are generally licensed under the terms of the [Creative Commons Attribute-ShareAlike 3.0 license](https://creativecommons.org/licenses/by-sa/3.0/legalcode.txt).  Modifications or submissions updated in this repository after the initial port are updated to the [Creative Commons Attribute-ShareAlike 4.0 license](https://creativecommons.org/licenses/by-sa/4.0/legalcode.txt) as defined at [LICENSE](LICENSE)


