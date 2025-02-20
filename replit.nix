{pkgs}: {
  deps = [
    pkgs.jre
    pkgs.glibcLocales
    pkgs.postgresql
    pkgs.openssl
  ];
}
