import os
import sys
import click
import functools
import tempfile
import subprocess
from pathlib import Path
from logging import getLogger
from .version import VERSION

_log = getLogger(__name__)


@click.version_option(version=VERSION, prog_name="localpkg")
@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


def set_verbose(verbose: bool | None):
    from logging import basicConfig

    fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    level = "INFO"
    if verbose:
        level = "DEBUG"
    elif verbose is not None:
        level = "WARNING"
    basicConfig(level=level, format=fmt)


def verbose_option(func):
    @functools.wraps(func)
    def wrap(verbose, *args, **kwargs):
        set_verbose(verbose)
        return func(*args, **kwargs)

    return click.option("--verbose/--quiet", default=None, help="log level")(wrap)


def base_option(func):
    @click.option("--python-bin", default="python", show_default=True)
    @click.option(
        "--python-name",
        default="python3",
        help="destination binary name of python",
        show_default=True,
    )
    @click.option("--name", default=Path.cwd().name, show_default=True)
    @click.option("--compile/--no-compile", default=False, show_default=True)
    @click.option("--zip/--no-zip", default=False, show_default=True)
    @click.argument("args", nargs=-1)
    @functools.wraps(func)
    def _(*a, **kw):
        return func(*a, **kw)

    return _


def package_option(func):
    @click.option("--maintainer", default="Watanabe Takashi <wtnb75@gmail.com>")
    @click.option("--version", default="0.0.1", show_default=True)
    @functools.wraps(func)
    def _(*a, **kw):
        return func(*a, **kw)

    return _


def _venv(python_bin, output_dir) -> Path:
    _log.debug("make venv to %s", output_dir)
    cmdres = subprocess.run([python_bin, "-m", "venv", "--system-site-packages", output_dir])
    cmdres.check_returncode()
    return Path(output_dir) / "bin" / "pip"


def _envvars(user_base) -> dict:
    _log.debug("make environ: userbase=%s", user_base)
    keepenv = {}
    env = {k: v for k, v in os.environ.items() if k in keepenv}
    env["PYTHONUSERBASE"] = user_base
    return env


def _pip_install(vpip_bin: Path, compile: bool, args: tuple[str], env: dict):
    _log.info("install: %s (compile=%s, pip=%s)", args, compile, vpip_bin)
    basearg = ["--disable-pip-version-check"]
    if compile:
        basearg.append("--compile")
    else:
        basearg.append("--no-compile")
    pipres = subprocess.run([vpip_bin, "install", "--user", *basearg, *args], env=env)
    pipres.check_returncode()


def _fixbin1(fn: Path, pkgdir: Path, python_name: str | None = None):
    _log.info("fix binary: %s pkgdir=%s, python=%s", fn, pkgdir, python_name)
    ofn = str(fn) + ".new"
    txt = fn.read_text()
    if not txt.startswith("#!/"):
        _log.debug("pass(shebang)")
        return
    python_name = python_name or "python"
    relpath = str(pkgdir.relative_to(fn, walk_up=True))
    pathadd = r"os.path.abspath(os.path.join(__file__, " + repr(relpath) + "))"
    with open(ofn, "w") as ofp:
        for line in txt.splitlines():
            if line.startswith("#!"):  # shebang
                ofp.write(f"#! /usr/bin/env {python_name}\n")
            elif line == "import sys":
                ofp.write(f"""import os
import sys
sys.path.insert(0, {pathadd})
""")
            else:
                ofp.write(line + "\n")
    os.chmod(ofn, 0o755)
    os.rename(ofn, fn)
    _log.info("command fixed: %s", fn)


def _fixbin(dn: Path, pkgdir: Path, python_name: str | None = None):
    for file in dn.glob("*"):
        if file.is_file() and os.access(file, os.X_OK):
            _fixbin1(file, pkgdir, python_name)


def _fixzip(sitedir: Path, ofn: Path, do_zip: bool = True) -> Path:
    import zipfile
    import shutil

    if do_zip:
        zf = zipfile.ZipFile(ofn, "w")
        for root, _, files in sitedir.walk():
            for fn in files:
                path = Path(root) / fn
                zf.write(
                    path,
                    path.relative_to(sitedir),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
                path.unlink()
        zf.close()
        shutil.rmtree(sitedir, ignore_errors=True)
        try:
            sitedir.parent.rmdir()
        except Exception:
            pass
        return ofn
    return sitedir


def _install(python_bin, destdir, python_name, name, compile, zip, prefix, args):
    with tempfile.TemporaryDirectory() as tdir:
        vpip_bin = _venv(python_bin, tdir)
        destdirp = Path(destdir)
        bindir = destdirp / prefix / "bin"
        libdir = destdirp / prefix / "lib"
        libzip = libdir / f"{name}.zip"
        sitepkg = libdir / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
        env = _envvars(destdirp / prefix)
        _pip_install(vpip_bin, compile, args, env)
        pathname = _fixzip(sitepkg, libzip, do_zip=zip)
        _fixbin(bindir, pathname, python_name)
        return pathname


def _tar(rootdir: Path, dest: Path, prefix: str):
    import tarfile

    with tarfile.open(dest, "w:gz") as tar:
        for root, _, files in rootdir.walk():
            rootp = Path(root)
            for fn in files:
                name = rootp / fn
                tar.add(name, prefix + str(name.relative_to(rootdir)))


@cli.command()
@verbose_option
@base_option
@click.option("--destdir", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--prefix", default="usr", show_default=True)
def install(python_bin, destdir, python_name, name, compile, zip, prefix, args):
    pathname = _install(
        python_bin=python_bin,
        destdir=destdir,
        python_name=python_name,
        name=name,
        compile=compile,
        zip=zip,
        prefix=prefix,
        args=args,
    )
    click.echo(f"PYTHONPATH={pathname}")


@cli.command()
@verbose_option
@base_option
def tar(python_bin, python_name, name, compile, zip, args):
    with tempfile.TemporaryDirectory() as work:
        workd = Path(work)
        pathname = _install(
            python_bin=python_bin,
            destdir=workd,
            python_name=python_name,
            name=name,
            compile=compile,
            zip=zip,
            prefix="usr",
            args=args,
        )
        _log.info("PYTHONPATH=/%s", pathname.relative_to(workd))
        src = Path(f"{name}.tar.gz")
        _tar(workd / "usr", src, f"{name}/usr/")


@cli.command()
@verbose_option
@base_option
@package_option
def deb(python_bin, python_name, name, compile, zip, version, maintainer, args):
    with tempfile.TemporaryDirectory() as work:
        workd = Path(work)
        pathname = _install(
            python_bin=python_bin,
            destdir=workd,
            python_name=python_name,
            name=name,
            compile=compile,
            zip=zip,
            prefix="usr",
            args=args,
        )
        (workd / "DEBIAN").mkdir()
        (workd / "DEBIAN" / "control").write_text(f"""
Package: {name}
Maintainer: {maintainer}
Architecture: all
Version: {version}
Depends: python3
Description: local package for {name}
  use as library: PYTHONPATH=/{pathname.relative_to(workd)}
""")
        subprocess.run(["fakeroot", "--", "dpkg-deb", "--root-owner-group", "--build", workd, "."]).check_returncode()


@cli.command()
@verbose_option
@base_option
@package_option
def rpm(python_bin, python_name, name, compile, zip, version, maintainer, args):
    import shutil

    with tempfile.TemporaryDirectory() as work:
        workd = Path(work)
        pathname = _install(
            python_bin=python_bin,
            destdir=workd,
            python_name=python_name,
            name=name,
            compile=compile,
            zip=zip,
            prefix="usr",
            args=args,
        )
        for n in ("BUILD", "RPMS", "SOURCES", "SPECS"):
            (workd / n).mkdir()
        src = workd / "SOURCES" / f"{name}-{version}.tar.gz"
        rpm = workd / "RPMS" / "noarch" / f"{name}-{version}-1.noarch.rpm"
        _tar(workd / "usr", src, f"{name}-{version}/usr/")
        specfn = workd / "SPECS" / f"{name}.spec"
        specfn.write_text(f"""
Summary: local package for {name}
Name: {name}
Version: {version}
Release: 1
BuildArch: noarch
License: Unknown
Packager: {maintainer}
Requires: python3
Source0: %{{name}}-%{{version}}.tar.gz
BuildRoot: %{{_tmppath}}/%{{name}}-%{{version}}-root

%description
local package for {name}
use as library: PYTHONPATH=/{pathname.relative_to(workd)}

%prep
rm -rf %{{buildroot}}

%setup -q

%build

%install
mkdir -p %{{buildroot}}/usr
cp -r usr/ %{{buildroot}}/usr

%clean
rm -rf %{{buildroot}}

%files
%defattr(-, root, root)
/usr/*/*
""")
        subprocess.run(["rpmbuild", "--define", f"_topdir {workd}", "-bb", specfn]).check_returncode()
        if not rpm.exists():
            _log.error("file: %s", list(rpm.parent.glob("*.rpm")))
        shutil.copy(rpm, ".")


@cli.command()
@verbose_option
@base_option
@package_option
def apk(python_bin, python_name, name, compile, zip, version, maintainer, args):
    subprocess.run(["abuild-sign", "-e"]).check_returncode()
    with tempfile.TemporaryDirectory() as work:
        workd = Path(work)
        pathname = _install(
            python_bin=python_bin,
            destdir=workd,
            python_name=python_name,
            name=name,
            compile=compile,
            zip=zip,
            prefix="usr",
            args=args,
        )
        (workd / "build").mkdir()
        src = workd / "build" / f"{name}-{version}.tar.gz"
        apk = workd / "build" / "APKBUILD"
        _tar(workd / "usr", src, f"{name}-{version}/usr/")
        apk.write_text(f"""
# Contributor: {maintainer}
# Maintainer: {maintainer}
pkgname={name}
pkgver={version}
pkgrel=1
pkgdesc="local package for {name}. if use as library: PYTHONPATH=/{pathname.relative_to(workd)}"
arch="noarch"
url="https://github.com/wtnb75/localpkg"
license="Unknown"
depends="python3"
makedepends=""
install=""
subpackages=""
source="{name}-{version}.tar.gz"
builddir="$srcdir/$pkgname-$pkgver"

prepare() {{
	:
}}

build() {{
	:
}}

check() {{
	:
}}

package() {{
	mkdir -p ${{pkgdir}}/usr
	cp -r ${{builddir}}/usr/ ${{pkgdir}}/
}}
""")
        subprocess.run(["abuild", "checksum"], cwd=workd / "build").check_returncode()
        subprocess.run(
            ["abuild", "-rF", "-P", os.getcwd()],
            cwd=workd / "build",
            env={"CARCH": "noarch"},
        ).check_returncode()


if __name__ == "__main__":
    cli()
