{pkgs}: {
  deps = [
    pkgs.poppler_utils
    pkgs.tesseract
    pkgs.jdk8
    pkgs.jre
    pkgs.glibcLocales
    pkgs.postgresql
    pkgs.openssl
  ];
}
