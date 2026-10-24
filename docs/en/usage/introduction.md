---
icon: material/book-open-variant
---

# Introduction and concepts

GerberSLAp turns the Gerber files of a printed circuit board into the **print file** of a resin printer with a monochrome LCD screen and 405 nm UV light. The printer thus becomes an **exposure unit** for **pre-sensitised** copper boards, that is boards already covered with photosensitive resist.

This chapter explains how it works in brief, what you need and the words the rest of the manual uses: plane, board, polarity, exposure, recipe, dosage.

## How it works

The work happens in a web page: you open the Gerber zip, place the board on a plane that represents the screen, choose the resist and the exposure and get a file to copy onto the printer's USB stick, since the printer has no network.

The printer “prints” **a single layer**, for the whole time chosen. On the LCD screen the white pixels let the UV light through and the black ones stop it: where the light arrives, the resist on the board is exposed. Then the board is developed and etched, and the drawing of the circuit remains.

The print file is not written from scratch: the app starts from a file made once with ChiTuBox, the printer's **template**, and changes the images and the exposure time. Everything else, such as the movement of the carriage, is copied from the template.

## What you need

- **A supported printer.** Today the Creality LD-002H (2K mono LCD) is supported. Other printers are added with a driver, without changing the rest of the app.
- **The printer template**: a `.ctb` file made with ChiTuBox and installed once. It is not part of the app because it contains the manufacturer's copyright notice. How to prepare it is explained in [Requirements and template](../installation/requirements.md#the-printer-template).
- **The app running**, locally or in a Docker container: see [Installing the app](../installation/install.md).
- **A recent browser.** Chrome is the one tried.
- **The circuit's Gerber files**, in a zip. KiCad, Altium and EAGLE 9 are recognised by themselves; old EAGLE exports are refused.
- **Pre-sensitised boards**, and what is needed to develop and etch them. This manual does not cover that part.

## The concepts

### Plane

The **plane** is the LCD screen seen from above, with Rulers in millimetres. On the LD-002H it measures 130.56 × 82.62 mm and has 2560 × 1620 pixels, each 0.051 mm wide. Everything is placed on the plane, and what falls outside is not exposed.

### Board and layer

A **board** is a Gerber zip added to the plane. It has a position, a rotation and, if needed, a mirror. You can have several boards on the plane, even copies of the same one. Boards are added and managed in the [Boards](boards.md) section; their position is chosen in [Placement](placement.md).

The files in the zip are the **layers**, and the app recognises by itself what each one is: **copper**, solder **mask**, **silkscreen**, **outline** and **drills**. Each layer can be switched on or off and has a status that says whether it was read well. The print file exposes the layers that are on at that moment.

### Mirror

If the board is laid with the copper facing the screen, the image has to be **mirrored** left to right. The mirror is the user's choice on the placed board and is seen at once in the preview.

### Resist polarity

It is the property of the resist that decides where the light must pass:

- with the **positive** resist the light passes where there is **no** copper;
- with the **negative** resist the light passes where there **is** copper.

It depends on the product used. The resist selector shows the positive in white and the negative in black.

### Exposure

The **exposure** is described by three values:

| Value | What it is |
|---|---|
| **Total time** | The seconds in which the light passes in all. It is the “dose”. |
| **Flashes** | How many pulses the total time is divided into: one flash of *T* seconds, or *N* flashes of *T/N*. |
| **Rest** | The seconds of darkness between one flash and the next. It only serves to let the LCD and the LEDs cool. |

The three values are chosen in the [Exposure](exposure.md) panel.

### Recipe and dosage

A **recipe** is what you do with a resist: it has a name, the polarity (which cannot be changed once created), the resist, the development and some notes. A recipe says nothing about the printer.

A **dosage** is the three exposure values (total time, flashes, rest) found by trying, for **one printer**, with the date and an optional note. A recipe can have several dosages: they are alternatives that all stay valid, for example for fine tracks or for large ground planes.

Recipes live on the app's server, in its data folder, and are shared by every browser that uses it. With the `--no-library` option the library is off and only the three values written by hand remain ([Configuration](../installation/configuration.md#with-and-without-the-recipe-library)).

### Calibration ladder

The **calibration ladder** is a test file with strips exposed for increasing times, used to find the right time for a resist. The result is saved as a dosage in a recipe. It is used in the [Calibration ladder](calibration-ladder.md) page.

### Printer and template

The **printer** is the type of machine (its driver), not the unit with its serial number. The **template** is the file from which the app copies the printer's movement, as seen above.

### Project

A **project** is the set of boards with their positions, the exposure and the chosen recipe. It is saved in the browser, as a working copy, and downloaded as a `.gslp` file, which also holds the Gerber files ([Projects](projects.md)). **The server does not keep projects.**

## The workflow

1. **Add the board**: drag the Gerber zip onto the page ([Boards](boards.md)).
2. **Place it** on the plane, with rotation and mirror ([Placement](placement.md)).
3. **Choose resist and exposure**, by hand or from a recipe ([Exposure](exposure.md)).
4. **The first time with a new resist**, find the right time with the calibration ladder and save it as a dosage ([Calibration ladder](calibration-ladder.md)).
5. **Generate the print file** ([Exposure](exposure.md)).
6. **Copy it onto the USB stick** and start the print from the printer ([From file to printer](printing.md)).
7. **Develop and etch** the board, outside GerberSLAp.

## Current limits

- It is a **single-sided** version: a file exposes the layers that are on at that moment. Alignment between successive exposures of the same board, for example for double-sided boards, is not handled.
- **Negative inner planes** are not supported.
- **A single printer** is supported, the Creality LD-002H.

!!! warning "What has not been tried"
    The calibration ladder's file, with its patterns and the time text on each strip, **has not yet been tried on the printer**. The file format, the image orientation and the movement have instead been verified on the printer with test files; a real board still has to be measured with calipers.

## How to read the manual

- Names such as **MenuBar**, **SidePanel** or **CadWindow** indicate the zones of the interface. The [Interface tour](interface.md) shows them one by one.
- Buttons that perform an action have only an icon: their name appears in a tooltip when you hover over them with the mouse.
- The coloured boxes mark notes, warnings and dangers; the red ones are not to be ignored.

The next chapter, [First steps](first-steps.md), takes you through preparing the first file, from the zip to the exposure.
