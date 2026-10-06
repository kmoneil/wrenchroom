# Security Policy

## Reporting a vulnerability

**Please report security issues privately, not as a public issue.**

- **Preferred:** [open a private security advisory](https://github.com/kmoneil/wrenchroom/security/advisories/new).
  It gives us a private thread, and it is the channel that can issue a CVE at the end.
- **If you cannot use GitHub, or would rather not:** email **kevin@oneil.xyz**. That is a real
  fallback, not a formality.

A small model file or sidecar that shows the problem helps most. Please make it a generic one: a
plate, a box, a screw. Never send geometry you are not free to share, yours or anybody else's.

## What is in scope

wrenchroom is a local tool that reads files a person hands it and writes reports. The bugs this
project considers its own:

- **A model or sidecar that makes wrenchroom do more than read it.** Executing code, writing a
  file it was not asked to write, or reading a file the sidecar did not name. The sidecar is
  read with a YAML safe loader and its `model:` entries name further STEP files to read; anything
  past that is a vulnerability here.
- **Injection into what a person reads.** Part names come from the model, and a model can come
  from anybody. A name that drives a terminal through escape sequences, or that lands in a report
  (JSON now, HTML later) in a way that runs script or changes its meaning, is in scope.
- **This repository's automation.** A way for a pull request to run code with more than the
  read-only token the workflows are given, or to bypass the checks that protect `main`.

## What is not in scope

- **Bugs in the CAD kernel and libraries underneath.** STEP files are parsed by OpenCascade
  (through OCP and build123d) and meshes are tested by manifold3d. A crash, hang or memory-safety
  bug in those parsers belongs to those projects; please report it there. Tell us as well if
  wrenchroom makes it easier to reach than it should be.
- **A wrong verdict.** A fastener reported reachable that isn't, or the other way round, is a
  serious bug and an ordinary one: open an issue, with a generic model that shows it.
- **A model that is simply big.** Checking takes time in proportion to the model. A file built to
  be slow is not a vulnerability unless it is out of all proportion to its size.
- **Someone who already runs code as your user.** Nothing here defends against that.

## Supported versions

**Nothing is released yet.** Until there is a release, fixes land on `main` and that is the only
supported version. After that: the latest release, and only the latest release, while the major
version is `0`.

## What to expect

This is a single-maintainer project, so these are realistic targets rather than a service level
agreement:

- **Acknowledgement within 5 business days.** If you have not heard back, assume the message went
  astray and try the other channel.
- **An assessment within 10 business days**: whether it is a vulnerability, and if so its severity
  and scope, with the reasoning if we disagree.
- **A fix, or a written decision not to fix, before any public disclosure.**
- **Coordinated disclosure, with 90 days as the default embargo**, negotiable either way, and
  shorter if the issue is being exploited.
- **Credit in the advisory**, unless you would rather not be named.
- **No bug bounty.** There is a fast, respectful response and public credit.
