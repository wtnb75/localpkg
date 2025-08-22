import os
import sys
import click
import functools
import tempfile
import subprocess
import shutil
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
    @click.option("--python-bin", default="python3", show_default=True, help="python to create venv")
    @click.option(
        "--python-name",
        default="python3",
        help="destination binary name of python",
        show_default=True,
    )
    @click.option("--name", default=Path.cwd().name, show_default=True, help="name of package")
    @click.option("--compile/--no-compile", default=False, show_default=True, help="compile .py to .pyc")
    @click.option("--zip/--no-zip", default=False, show_default=True, help="use zipimport")
    @click.argument("args", nargs=-1, required=True)
    @functools.wraps(func)
    def _(*a, **kw):
        return func(*a, **kw)

    return _


def package_option(func):
    @click.option("--maintainer", default="Watanabe Takashi <wtnb75@gmail.com>", help="maintainer name")
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
    keepenv = {"http_proxy", "https_proxy", "no_proxy"}
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
    try:
        txt = fn.read_text()
    except Exception:
        _log.error("failed to read file: %s", fn)
        return
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

    if do_zip:
        zf = zipfile.ZipFile(ofn, "w")
        exists = False
        for root, _, files in sitedir.walk():
            for fn in files:
                path = Path(root) / fn
                zf.write(
                    path,
                    path.relative_to(sitedir),
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
                exists = True
                path.unlink()
        zf.close()
        if not exists:
            ofn.unlink()
        shutil.rmtree(sitedir, ignore_errors=True)
        try:
            sitedir.parent.rmdir()
            sitedir.parent.parent.rmdir()
        except Exception:
            pass
        return ofn
    # move site-packages to ofn
    newdir = ofn.with_suffix("")
    sitedir.rename(newdir)
    return newdir


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

    def _filt(input: tarfile.TarInfo) -> tarfile.TarInfo:
        return input.replace(uid=0, gid=0, uname="root", gname="root", deep=False)

    with tarfile.open(dest, "w:gz") as tar:
        for root, _, files in rootdir.walk():
            rootp = Path(root)
            for fn in files:
                name = rootp / fn
                tar.add(name, prefix + str(name.relative_to(rootdir)), recursive=False, filter=_filt)


@cli.command()
@verbose_option
@base_option
@click.option("--destdir", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--prefix", default="usr", show_default=True)
def install(python_bin, destdir, python_name, name, compile, zip, prefix, args):
    """install to DESTDIR"""
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
@click.option("--prefix", default="usr", show_default=True)
@click.option("--version", default="0.0.1", show_default=True)
def tar(python_bin, python_name, name, compile, zip, version, prefix, args):
    """create .tar.gz package"""
    pfx = prefix.strip("/")
    tar_prefix = f"{name}-{version}/{pfx}/"
    with tempfile.TemporaryDirectory() as work:
        workd = Path(work)
        pathname = _install(
            python_bin=python_bin,
            destdir=workd,
            python_name=python_name,
            name=name,
            compile=compile,
            zip=zip,
            prefix=pfx,
            args=args,
        )
        _log.info("PYTHONPATH=/%s", pathname.relative_to(workd))
        src = Path(f"{name}-{version}.tar.gz")
        _tar(workd / "usr", src, tar_prefix)


@cli.command()
@verbose_option
@base_option
@package_option
def deb(python_bin, python_name, name, compile, zip, version, maintainer, args):
    """create .deb package for debian variants"""
    assert shutil.which("fakeroot")
    assert shutil.which("dpkg-deb")
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
    """create .rpm package for redhat variants"""
    assert shutil.which("rpmbuild")
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
cd usr
cp -r . %{{buildroot}}/usr/

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
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False, dir_okay=True),
    default=os.getcwd(),
    show_default=True,
    help="output directory",
)
@click.option("--key", type=click.Path(exists=True, dir_okay=False), required=True, help="openssh private key to sign")
def apk(python_bin, python_name, name, compile, zip, version, maintainer, key, output_dir, args):
    """create .apk package for alpine linux"""
    assert shutil.which("abuild")
    keytext = Path(key).read_text()
    res = subprocess.run(["ssh-keygen", "-f", key, "-y"], capture_output=True, encoding="utf-8")
    res.check_returncode()
    pubkey = res.stdout.strip()
    with tempfile.TemporaryDirectory() as work:
        keyfn = Path(work) / "packager.key"
        keyfn_p = keyfn.with_name("packager.key.pub")
        keyfn.write_text(keytext)
        keyfn_p.write_text(pubkey)
        env = {"PACKAGER_PRIVKEY": keyfn, "CARCH": "noarch"}
        subprocess.run(["abuild-sign", "-e"], env=env).check_returncode()
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
        (workd / "dest").mkdir()
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
        build_res = subprocess.run(
            ["abuild", "-rF", "-P", workd / "dest"],
            cwd=workd / "build",
            env=env,
        )
        created = False
        for root, _, files in (workd / "dest").walk():
            _log.info("files: root=%s, files=%s", root, files)
            for fn in files:
                if fn.endswith(".apk"):
                    src = Path(root) / fn
                    _log.info("copy: %s -> %s", src, output_dir)
                    created = True
                    shutil.copy(src, output_dir)
        if not created:
            build_res.check_returncode()


@cli.command()
@verbose_option
@base_option
@package_option
def pacman(python_bin, python_name, name, compile, zip, version, maintainer, args):
    """create pacman package for archlinux"""
    assert shutil.which("makepkg")
    assert shutil.which("debugedit")
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
        src = workd / f"{name}-{version}.tar.gz"
        _tar(workd / "usr", src, f"{name}-{version}/usr/")
        pkgbuild = workd / "PKGBUILD"
        pkgbuild.write_text(f"""
# mainteiner: {maintainer}
pkgname="{name}"
pkgver="{version}"
pkgrel="1"
pkgdesc="local package for {name}. if use as library: PYTHONPATH=/{pathname.relative_to(workd)}"
depends=("python")
license=("unknown")
source=("{src.name}")
sha512sums=("SKIP")

package(){{
    mkdir -p "${{pkgdir}}"
    tar xfz ${{srcdir}}/${{source}} -C ${{pkgdir}}
    mv ${{pkgdir}}/*/usr ${{pkgdir}}
    rmdir ${{pkgdir}}/* || true
}}
""")
        subprocess.run(["makepkg", "-A"], cwd=workd).check_returncode()
        for f in workd.glob("*.pkg.tar.zst"):
            _log.info("copying package: %s", f)
            shutil.copy(f, ".")


@cli.command()
@click.option("--key", type=click.Path(exists=True, dir_okay=False), help="gpg key to sign")
@click.argument("files", nargs=-1, type=click.Path(exists=True, dir_okay=False))
def rpm_sign(key, files):
    """TODO: sign .rpm package"""
    assert shutil.which("rpm")
    # TODO: prepare key
    for f in files:
        _log.info("signing: %s", f)
        subprocess.run(["rpm", "--addsign", f]).check_returncode()


@cli.command()
@click.option("--key", type=click.Path(exists=True, dir_okay=False), help="gpg key to sign")
@click.argument("files", nargs=-1, type=click.Path(exists=True, dir_okay=False))
def deb_sign(key, files):
    """TODO: sign .deb package"""
    assert shutil.which("debsigs")
    # TODO: prepare key
    for f in files:
        _log.info("signing: %s", f)
        subprocess.run(["debsigs", "--sign=maint", f]).check_returncode()


if __name__ == "__main__":
    cli()
