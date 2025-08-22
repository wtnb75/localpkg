# localpkg: Create OS Packages from pip-installed Python Software

`localpkg` is a tool for converting Python packages into native OS package formats (e.g., .rpm, .deb, .apk, etc.).
It automatically bundles dependencies and helps you package your Python projects, making distribution and installation on various operating systems simple and efficient.

Main features:

- Convert Python packages to native package formats.
- Simplify distribution and installation across different package systems.
- Support local package management.

## install

- (pip)
    - `pip install localpkg`
    - or `pip install git+https://github.com/wtnb75/localpkg/`
- (alpine)
    - `wget https://wtnb75.github.io/localpkg/pkg/localpkg-0.0.1-r1.apk`
    - `apk add localpkg-0.0.1-r1.apk --allow-untrusted`
- (debian/ubuntu)
    - `curl -LO https://wtnb75.github.io/localpkg/pkg/localpkg_0.0.1_all.deb`
    - `apt install ./localpkg_0.0.1_all.deb`
- (redhat variant)
    - `dnf localinstall https://wtnb75.github.io/localpkg/pkg/localpkg-0.0.1-1.noarch.rpm`
- (archlinux)
    - `curl -LO https://wtnb75.github.io/localpkg/pkg/localpkg-0.0.1-1-x86_64.pkg.tar.zst`
    - `pacman -U ./localpkg-0.0.1-1-x86_64.pkg.tar.zst`

## Usage

- create tarball
    - localpkg tar --name (pkgname) --version (version) -- (pip arguments)
- create .apk
    - localpkg apk --name (pkgname) --version (version) --key (private-keyfile) -- (pip arguments)
- create .deb
    - localpkg deb --name (pkgname) --version (version) -- (pip arguments)
- create .rpm
    - localpkg rpm --name (pkgname) --version (version) -- (pip arguments)
- create pacman
    - localpkg pacman --name (pkgname) --version (version) -- (pip arguments)
