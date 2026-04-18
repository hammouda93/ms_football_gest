function readTextFile(path) {
    var f = new File(path);
    if (!f.exists) {
        throw new Error("Fichier introuvable: " + path);
    }
    if (!f.open("r")) {
        throw new Error("Impossible d'ouvrir le fichier: " + path);
    }
    var content = f.read();
    f.close();
    return content;
}

function writeTextFile(path, content) {
    var f = new File(path);
    if (!f.open("w")) {
        throw new Error("Impossible d'écrire le fichier: " + path);
    }
    f.write(content);
    f.close();
}

function findOrCreateBin(binName) {
    var root = app.project.rootItem;

    for (var i = 0; i < root.children.numItems; i++) {
        var item = root.children[i];
        if (item && item.name === binName && item.type === 2) {
            return item;
        }
    }

    return root.createBin(binName);
}

function collectImportedProjectItems(bin) {
    var items = [];
    for (var i = 0; i < bin.children.numItems; i++) {
        var item = bin.children[i];
        if (item && item.type === 1) {
            items.push(item);
        }
    }
    return items;
}

function main() {
    // A adapter si besoin
    var jobPath = "D:/Django_Projects/ms_football_gest/gestion_joueurs/automated_players/1745_Islem_Chelghoumi/premiere/premiere_job.json";

    try {
        var job = JSON.parse(readTextFile(jobPath));

        app.project.saveAs(job.project_path);

        var rawBin = findOrCreateBin(job.raw_bin_name || "01_RAW");

        app.project.importFiles(job.clips, 1, rawBin, 0);

        var importedItems = collectImportedProjectItems(rawBin);
        if (!importedItems.length) {
            throw new Error("Aucun clip importé");
        }

        var seqName = job.sequence_name || "REVIEW_TIMELINE";
        var sequence = app.project.createNewSequenceFromClips(seqName, importedItems, rawBin);
        if (!sequence) {
            throw new Error("Impossible de créer la séquence");
        }

        app.project.save();

        var resultPath = job.premiere_dir + "/premiere_result.json";
        writeTextFile(resultPath, JSON.stringify({
            success: true,
            project_path: job.project_path,
            sequence_name: seqName,
            clips_count: job.clips.length
        }, null, 2));
    } catch (e) {
        var fallbackResult = {
            success: false,
            error: e.toString()
        };

        try {
            writeTextFile("D:/temp/premiere_result_error.json", JSON.stringify(fallbackResult, null, 2));
        } catch (_) {
        }

        throw e;
    }
}

main();