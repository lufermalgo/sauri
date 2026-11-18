// Fills the «Descargar» section from the release config block (#sauri-release) at the top of index.html.
// A link is enabled only when its URL is a real https address; anything else keeps the button disabled with
// «Disponible pronto». The checksum and version are shown only when they are set and well formed.
(function () {
  var config = {};
  try {
    var block = document.getElementById("sauri-release");
    config = JSON.parse(block ? block.textContent : "{}") || {};
  } catch (error) {
    config = {};
  }

  function realUrl(value) {
    if (typeof value !== "string" || !value.trim()) return null;
    try {
      var url = new URL(value.trim());
      var host = url.hostname.toLowerCase();
      var placeholder = /\.invalid$|\.example$|\.test$|^example\.(com|org|net)$|^localhost$/.test(host);
      return url.protocol === "https:" && !placeholder ? url.href : null;
    } catch (error) {
      return null;
    }
  }

  function enable(link, href, label) {
    link.href = href;
    link.removeAttribute("aria-disabled");
    if (label) link.textContent = label;
  }

  var version = typeof config.version === "string" ? config.version.trim() : "";
  var download = realUrl(config.downloadUrl);
  var store = realUrl(config.chromeWebStoreUrl);
  var sha = typeof config.sha256 === "string" ? config.sha256.trim().toLowerCase() : "";

  document.querySelectorAll("[data-download-url]").forEach(function (link) {
    if (download) enable(link, download, "Descargar Sauri para Mac");
  });
  document.querySelectorAll("[data-store-url]").forEach(function (link) {
    if (store) {
      enable(link, store, "Agregar a Chrome");
      link.rel = "noopener";
    }
  });
  document.querySelectorAll("[data-release-version]").forEach(function (node) {
    if (version && download) {
      node.textContent = "Versión " + version;
      node.hidden = false;
    }
  });
  if (/^[0-9a-f]{64}$/.test(sha) && download) {
    document.querySelectorAll("[data-release-sha-value]").forEach(function (node) { node.textContent = sha; });
    document.querySelectorAll("[data-release-sha]").forEach(function (node) { node.hidden = false; });
  }
})();
