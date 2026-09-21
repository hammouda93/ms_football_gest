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

      var positionCategories = {
        goalkeeper: [
          { code: "0", label: "CLOSEUP", text: "Closeup" },
          { code: "1", label: "SUPERSAVE", text: "Super Save" },
          { code: "2", label: "BESTCROSSSAVE", text: "Best Cross Save" },
          { code: "3", label: "GREATFOOTPLAY", text: "Great Foot Play" },
          { code: "4", label: "HANDDISTRIBUTION", text: "Hand Distribution" },
          { code: "5", label: "CLEARANCE", text: "Clearance" },
          { code: "6", label: "NORMALSAVE", text: "Normal Save" },
          { code: "7", label: "NORMALCROSSSAVE", text: "Normal Cross Save" },
          { code: "8", label: "SWEEPERACTION", text: "Sweeper Action" },
          { code: "9", label: "OTHER", text: "Other" }
        ],
        central_defender: [
          { code: "0", label: "CLOSEUP", text: "Closeup" },
          { code: "1", label: "GOAL", text: "Goal" },
          { code: "2", label: "ASSIST", text: "Assist" },
          { code: "3", label: "BESTDEFENSIVEACTION", text: "Best Defensive Action" },
          { code: "4", label: "BESTPASS", text: "Best Pass" },
          { code: "5", label: "INTERCEPTION", text: "Interception" },
          { code: "6", label: "CROSSDEFENSE", text: "Cross Defense" },
          { code: "7", label: "HEADER", text: "Header" },
          { code: "8", label: "NORMALCHALLENGE", text: "Normal Challenge" },
          { code: "9", label: "NORMALPASS", text: "Normal Pass" }
        ],
        fullback: [
          { code: "0", label: "CLOSEUP", text: "Closeup" },
          { code: "1", label: "GOAL", text: "Goal" },
          { code: "2", label: "ASSIST", text: "Assist" },
          { code: "3", label: "KEYPASS", text: "Key Pass" },
          { code: "4", label: "BESTOFFENSIVEACTION", text: "Best Offensive Action" },
          { code: "5", label: "DRIBBLE", text: "Dribble" },
          { code: "6", label: "BESTDEFENSIVEACTION", text: "Best Defensive Action" },
          { code: "7", label: "NORMALPASS", text: "Normal Pass" },
          { code: "8", label: "NORMALDEFENSIVEACTION", text: "Normal Defensive Action" },
          { code: "9", label: "OTHER", text: "Other" }
        ],
        defensive_midfielder: [
          { code: "0", label: "CLOSEUP", text: "Closeup" },
          { code: "1", label: "GOAL", text: "Goal" },
          { code: "2", label: "ASSIST", text: "Assist" },
          { code: "3", label: "KEYPASS", text: "Key Pass" },
          { code: "4", label: "BESTOFFENSIVEACTION", text: "Best Offensive Action" },
          { code: "5", label: "BESTDEFENSIVEACTION", text: "Best Defensive Action" },
          { code: "6", label: "GREATPASS", text: "Great Pass" },
          { code: "7", label: "NORMALPASS", text: "Normal Pass" },
          { code: "8", label: "NORMALCHALLENGE", text: "Normal Challenge" },
          { code: "9", label: "OTHER", text: "Other" }
        ],
        attacking_midfielder: [
          { code: "0", label: "CLOSEUP", text: "Closeup" },
          { code: "1", label: "GOAL", text: "Goal" },
          { code: "2", label: "ASSIST", text: "Assist" },
          { code: "3", label: "KEYPASS", text: "Key Pass" },
          { code: "4", label: "BESTOFFENSIVEACTION", text: "Best Offensive Action" },
          { code: "5", label: "DRIBBLE", text: "Dribble" },
          { code: "6", label: "CHALLENGE", text: "Challenge" },
          { code: "7", label: "GREATPASS", text: "Great Pass" },
          { code: "8", label: "HEADER", text: "Header" },
          { code: "9", label: "OTHER", text: "Other" }
        ],
        winger: [
          { code: "0", label: "CLOSEUP", text: "Closeup" },
          { code: "1", label: "GOAL", text: "Goal" },
          { code: "2", label: "ASSIST", text: "Assist" },
          { code: "3", label: "KEYPASS", text: "KeyPass" },
          { code: "4", label: "BESTACTION", text: "BestAction" },
          { code: "5", label: "DRIBBLE", text: "Dribble" },
          { code: "6", label: "CHALLENGE", text: "Challenge" },
          { code: "7", label: "GREATPASS", text: "GreatPass" },
          { code: "8", label: "HEADER", text: "Header" },
          { code: "9", label: "OTHER", text: "Other" }
        ],
        striker: [
          { code: "0", label: "CLOSEUP", text: "Closeup" },
          { code: "1", label: "GOAL", text: "Goal" },
          { code: "2", label: "ASSIST", text: "Assist" },
          { code: "3", label: "KEYPASS", text: "KeyPass" },
          { code: "4", label: "BESTACTION", text: "BestAction" },
          { code: "5", label: "DRIBBLE", text: "Dribble" },
          { code: "6", label: "CHALLENGE", text: "Challenge" },
          { code: "7", label: "GREATPASS", text: "GreatPass" },
          { code: "8", label: "HEADER", text: "Header" },
          { code: "9", label: "OTHER", text: "Other" }
        ]
      };

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

      function exportFinalVideo() {
        setStatus("Export direct de COMPLETED_MAIN dans Premiere Pro...");
        cs.evalScript('$._MSBridge.exportCompletedMain()', function (result) {
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

      function renderCategories(positionKey) {
        var categories = positionCategories[positionKey] || positionCategories.striker;
        var grid = document.getElementById("categories-grid");

        while (grid.firstChild) {
          grid.removeChild(grid.firstChild);
        }

        for (var i = 0; i < categories.length; i++) {
          var category = categories[i];
          var button = document.createElement("button");
          var code = document.createElement("span");

          button.type = "button";
          button.className = "cat-btn";
          button.setAttribute("data-code", category.code);
          button.setAttribute("data-label", category.label);

          code.className = "cat-code";
          code.textContent = category.code;

          button.appendChild(code);
          button.appendChild(document.createTextNode(category.text));
          button.addEventListener("click", function () {
            applyCategory(
              this.getAttribute("data-code"),
              this.getAttribute("data-label")
            );
          });

          grid.appendChild(button);
        }
      }

      document.getElementById("run-now").addEventListener("click", runCommand);
      document.getElementById("refresh-summary").addEventListener("click", refreshSummary);
      document.getElementById("build-final").addEventListener("click", buildAssemblyMain);
      document.getElementById("build-styled").addEventListener("click", buildStyledMain);
      document.getElementById("build-completed").addEventListener("click", buildCompletedMain);
      document.getElementById("export-final").addEventListener("click", exportFinalVideo);

      document.getElementById("mark-slowmo").addEventListener("click", function () {
        applyStyle("SLOWMO");
      });

      document.getElementById("mark-reverse").addEventListener("click", function () {
        applyStyle("REVERSE");
      });

      var positionSelector = document.getElementById("player-position");
      positionSelector.addEventListener("change", function () {
        renderCategories(this.value);
      });
      renderCategories(positionSelector.value);

      runCommand();

    } catch (e) {
      setStatus("Erreur CSInterface: " + e);
    }
  });
})();
