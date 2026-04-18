(function () {
  function setStatus(msg) {
    document.getElementById("status").textContent = msg;
  }

  function escapeForEval(str) {
    return String(str).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  }

  document.addEventListener("DOMContentLoaded", function () {
    try {
      var cs = new CSInterface();

      function runCommand() {
        setStatus("Création projet Premiere...");
        cs.evalScript('$._MSBridge.runCreateProjectFromCurrentCommand()', function (result) {
          setStatus("Résultat: " + result);
        });
      }

      function refreshSummary() {
        cs.evalScript('$._MSBridge.getReviewSummary()', function (result) {
          setStatus("Résultat: " + result);
        });
      }

      function buildAssemblyMain() {
        setStatus("Construction ASSEMBLY_MAIN...");
        cs.evalScript('$._MSBridge.buildFinalMainFromMarkers()', function (result) {
          setStatus("Résultat: " + result);
        });
      }

      function buildStyledMain() {
        setStatus("Construction STYLED_MAIN...");
        cs.evalScript('$._MSBridge.copyAssemblyToStyledMain()', function (result) {
          setStatus("Résultat: " + result);
        });
      }

      function buildCompletedMain() {
        setStatus("Construction COMPLETED_MAIN...");
        cs.evalScript('$._MSBridge.buildCompletedMainFromStyled()', function (result) {
          setStatus("Résultat: " + result);
        });
      }

      function applyCategory(code, label) {
        var script = '$._MSBridge.applyCategoryToLastTwoMarkers("' +
          escapeForEval(code) + '","' + escapeForEval(label) + '")';

        cs.evalScript(script, function (result) {
          setStatus("Résultat: " + result);
        });
      }

      function applyStyle(styleCode) {
        var script = '$._MSBridge.applyStyleToLastTwoMarkersInAssembly("' +
          escapeForEval(styleCode) + '")';

        cs.evalScript(script, function (result) {
          setStatus("Résultat: " + result);
        });
      }

      document.getElementById("run-now").addEventListener("click", runCommand);
      document.getElementById("refresh-summary").addEventListener("click", refreshSummary);
      document.getElementById("build-final").addEventListener("click", buildAssemblyMain);
      document.getElementById("build-styled").addEventListener("click", buildStyledMain);
      document.getElementById("build-completed").addEventListener("click", buildCompletedMain);

      document.getElementById("mark-slowmo").addEventListener("click", function () {
        applyStyle("SLOWMO");
      });

      document.getElementById("mark-reverse").addEventListener("click", function () {
        applyStyle("REVERSE");
      });

      var buttons = document.querySelectorAll(".cat-btn");
      for (var i = 0; i < buttons.length; i++) {
        buttons[i].addEventListener("click", function () {
          var code = this.getAttribute("data-code");
          var label = this.getAttribute("data-label");
          applyCategory(code, label);
        });
      }

      runCommand();

    } catch (e) {
      setStatus("Erreur CSInterface: " + e);
    }
  });
})();