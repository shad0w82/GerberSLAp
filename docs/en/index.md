---
hide:
  - navigation
  - toc
---

# GerberSLAp

**From Gerber files to the print file.** GerberSLAp uses a resin printer with a monochrome LCD screen and 405 nm UV light as an exposure unit for printed circuit boards on pre-sensitised copper: you open the Gerber zip, place the board on the plane that represents the screen, choose the exposure and copy the print file onto the printer's USB stick.

[Start with the manual](usage/introduction.md){ .md-button .md-button--primary }
[Install the app](installation/requirements.md){ .md-button }

<div class="grid cards" markdown>

-   :material-download-circle-outline: **Installation**

    ---

    Requirements, the printer template, native or Docker installation, configuration and updates.

    [:octicons-arrow-right-24: Installing the app](installation/requirements.md)

-   :material-book-open-variant: **Usage**

    ---

    The manual: from the Gerber zip to the print file, through placement, exposure and the calibration ladder.

    [:octicons-arrow-right-24: Introduction and concepts](usage/introduction.md)

-   :material-source-pull: **Development**

    ---

    Contributing to the project, trying changes and adding the driver of a new printer.

    [:octicons-arrow-right-24: Contributing](development/contributing.md)

-   :material-sitemap-outline: **Architecture**

    ---

    How the app is built: the principles, the code layers, the pipeline that builds the mask, the server and the page.

    [:octicons-arrow-right-24: Overview](architecture/overview.md)

</div>

!!! warning "First version"
    Today a single printer is supported, the Creality LD-002H, and the work is single-sided. The calibration ladder's file has not yet been tried on the printer: the limits are listed in [Introduction and concepts](usage/introduction.md#current-limits).

GerberSLAp is free software (GNU AGPL-3.0) and its code is on [GitHub](https://github.com/shad0w82/GerberSLAp). It is not affiliated with or endorsed by CBD Technology, Creality or ChiTuBox: their names and trademarks belong to their respective owners and are used here only to say what it is compatible with.
