if (typeof $._MSBridge === "undefined") {
    $._MSBridge = {};
}

$._MSBridge.readTextFile = function (path) {
    var f = new File(path);
    if (!f.exists) {
        throw new Error("File not found: " + path);
    }
    if (!f.open("r")) {
        throw new Error("Cannot open file: " + path);
    }
    var content = f.read();
    f.close();
    return content;
};

$._MSBridge.writeTextFile = function (path, content) {
    var f = new File(path);
    if (!f.open("w")) {
        throw new Error("Cannot write file: " + path);
    }
    f.write(content);
    f.close();
};

$._MSBridge.parseJsonText = function (text) {
    return eval("(" + text + ")");
};

$._MSBridge.findOrCreateBin = function (binName) {
    var root = app.project.rootItem;

    for (var i = 0; i < root.children.numItems; i++) {
        var item = root.children[i];
        if (item && item.name === binName && item.type === 2) {
            return item;
        }
    }
    return root.createBin(binName);
};

$._MSBridge.findProjectItemByName = function (parentBin, itemName) {
    for (var i = 0; i < parentBin.children.numItems; i++) {
        var item = parentBin.children[i];
        if (item && item.name === itemName) {
            return item;
        }
    }
    return null;
};

$._MSBridge.collectImportedProjectItems = function (bin) {
    var items = [];
    for (var i = 0; i < bin.children.numItems; i++) {
        var item = bin.children[i];
        if (item && item.type === 1) {
            items.push(item);
        }
    }
    return items;
};


$._MSBridge.runCreateProjectFromCurrentCommand = function () {
    var currentCommandPath = "D:/Django_Projects/ms_football_gest/gestion_joueurs/premiere_bridge/current_command.txt";

    try {
        var commandPath = $._MSBridge.readTextFile(currentCommandPath).replace(/^\s+|\s+$/g, "");
        if (!commandPath) {
            return "NO_COMMAND_FILE";
        }

        var commandText = $._MSBridge.readTextFile(commandPath);
        var command = $._MSBridge.parseJsonText(commandText);

        var jobText = $._MSBridge.readTextFile(command.job_file);
        var job = $._MSBridge.parseJsonText(jobText);

        var resultPath = job.premiere_dir + "/premiere_result.txt";
        var lockPath = job.premiere_dir + "/premiere_lock.txt";

        var lockFile = new File(lockPath);
        if (lockFile.exists) {
            return "LOCK_EXISTS";
        }
        $._MSBridge.writeTextFile(lockPath, "running");

        var created = app.newProject(job.project_path);
        if (!created) {
            throw new Error("app.newProject failed: " + job.project_path);
        }

        $.sleep(1500);

        var rawBin = $._MSBridge.findOrCreateBin(job.raw_bin_name || "01_RAW");
        var graphicsBin = $._MSBridge.findOrCreateBin(job.graphics_bin_name || "04_GRAPHICS");
        var audioBin = $._MSBridge.findOrCreateBin(job.audio_bin_name || "05_AUDIO");

        // importer clips joueur
        app.project.importFiles(job.clips, 1, rawBin, 0);

        var importedItems = $._MSBridge.collectImportedProjectItems(rawBin);
        if (!importedItems.length) {
            throw new Error("No imported clips found");
        }

        // importer logo
        if (!job.logo_path) {
            throw new Error("logo_path manquant dans le job");
        }

        var logoFile = new File(job.logo_path);
        if (!logoFile.exists) {
            throw new Error("Logo introuvable: " + job.logo_path);
        }

        app.project.importFiles([job.logo_path], 1, graphicsBin, 0);

        var logoItem = $._MSBridge.findProjectItemByName(graphicsBin, logoFile.name);
        if (!logoItem) {
            throw new Error("Logo importé mais introuvable dans 04_GRAPHICS");
        }

        // importer intro joueur si elle existe
        var introImported = false;
        if (job.player_intro_path) {
            var introFile = new File(job.player_intro_path);
            if (introFile.exists) {
                app.project.importFiles([job.player_intro_path], 1, graphicsBin, 0);
                introImported = true;
            }
        }

        // importer toutes les musiques si le dossier existe
        var musicFilesFound = 0;
        if (job.music_dir) {
            var musicFolder = new Folder(job.music_dir);
            if (musicFolder.exists) {
                var musicFiles = musicFolder.getFiles(function (f) {
                    if (!(f instanceof File)) {
                        return false;
                    }
                    var n = f.name ? f.name.toLowerCase() : "";
                    return /\.(mp3|wav|aif|aiff|m4a)$/.test(n);
                });

                musicFilesFound = musicFiles.length;

                if (musicFiles.length > 0) {
                    var musicPaths = [];
                    for (var mf = 0; mf < musicFiles.length; mf++) {
                        musicPaths.push(musicFiles[mf].fsName);
                    }

                    app.project.importFiles(musicPaths, 1, audioBin, 0);
                }
            }
        }

        // ordre final : logo puis clips
        var orderedItems = [logoItem];
        for (var i = 0; i < importedItems.length; i++) {
            orderedItems.push(importedItems[i]);
        }

        var seqName = job.sequence_name || "REVIEW_TIMELINE";
        var seq = app.project.createNewSequenceFromClips(seqName, orderedItems, rawBin);
        if (!seq) {
            throw new Error("Sequence creation failed");
        }

        app.project.save();

        $._MSBridge.writeTextFile(
            resultPath,
            "success=true\n" +
            "project_path=" + job.project_path + "\n" +
            "sequence_name=" + seqName + "\n" +
            "clips_count=" + job.clips.length + "\n" +
            "logo_path=" + job.logo_path + "\n" +
            "intro_imported=" + introImported + "\n" +
            "music_files_found=" + musicFilesFound + "\n"
        );

        return "SUCCESS | project=" + job.project_path +
               " | sequence=" + seqName +
               " | clips=" + job.clips.length +
               " | logo=OK" +
               " | intro_imported=" + (introImported ? "YES" : "NO") +
               " | music_found=" + musicFilesFound;
    } catch (e) {
        return "RUN_ERROR: " + e.toString();
    }
};


$._MSBridge.getActiveSequence = function () {
    if (!app.project || !app.project.activeSequence) {
        throw new Error("Aucune séquence active");
    }
    return app.project.activeSequence;
};

$._MSBridge.markerIsTagged = function (marker) {
    if (!marker) {
        return false;
    }
    var n = marker.name ? String(marker.name) : "";
    var c = marker.comments ? String(marker.comments) : "";
    return n.indexOf("CAT=") === 0 || c.indexOf("CAT=") === 0;
};

$._MSBridge.getLastTwoMarkers = function () {
    var seq = $._MSBridge.getActiveSequence();
    var markers = seq.markers;

    if (!markers || markers.numMarkers < 2) {
        throw new Error("Il faut au moins 2 marqueurs dans la séquence active");
    }

    var lastMarker = markers.getLastMarker();
    if (!lastMarker) {
        throw new Error("Impossible de récupérer le dernier marqueur");
    }

    var prevMarker = markers.getPrevMarker(lastMarker);
    if (!prevMarker) {
        throw new Error("Impossible de récupérer l'avant-dernier marqueur");
    }

    return [prevMarker, lastMarker];
};

$._MSBridge.getLastTwoUntaggedMarkers = function () {
    var seq = $._MSBridge.getActiveSequence();
    var markers = seq.markers;

    if (!markers || markers.numMarkers < 2) {
        throw new Error("Il faut au moins 2 marqueurs dans la séquence active");
    }

    var ordered = [];
    var current = markers.getFirstMarker();

    while (current) {
        ordered.push(current);
        current = markers.getNextMarker(current);
    }

    var untagged = [];
    for (var i = ordered.length - 1; i >= 0; i--) {
        if (!$._MSBridge.markerIsTagged(ordered[i])) {
            untagged.push(ordered[i]);
            if (untagged.length === 2) {
                break;
            }
        }
    }

    if (untagged.length < 2) {
        throw new Error("Impossible de trouver 2 marqueurs non tagués");
    }

    // on renvoie dans l'ordre chronologique
    var markerA = untagged[1];
    var markerB = untagged[0];

    try {
        if (markerA.start.seconds > markerB.start.seconds) {
            var tmp = markerA;
            markerA = markerB;
            markerB = tmp;
        }
    } catch (e) {
    }

    return [markerA, markerB];
};


$._MSBridge.applyCategoryToLastTwoMarkers = function (categoryCode, categoryLabel) {
    try {
        var pair = $._MSBridge.getLastTwoUntaggedMarkers();
        var startMarker = pair[0];
        var endMarker = pair[1];

        var cat = "CAT=" + categoryCode + "_" + categoryLabel;

        startMarker.name = cat + "_START";
        startMarker.comments = cat;

        endMarker.name = cat + "_END";
        endMarker.comments = cat;

        return "OK | " + cat;
    } catch (e) {
        return "TAG_ERROR: " + e.toString();
    }
};

$._MSBridge.getReviewSummary = function () {
    try {
        var seq = $._MSBridge.getActiveSequence();
        var markers = seq.markers;

        if (!markers || markers.numMarkers === 0) {
            return "NO_MARKERS";
        }

        var current = markers.getFirstMarker();
        var total = 0;
        var tagged = 0;

        while (current) {
            total += 1;
            if ($._MSBridge.markerIsTagged(current)) {
                tagged += 1;
            }
            current = markers.getNextMarker(current);
        }

        return "SUMMARY | total_markers=" + total + " | tagged_markers=" + tagged;
    } catch (e) {
        return "SUMMARY_ERROR: " + e.toString();
    }
};









$._MSBridge.findSequenceByName = function (sequenceName) {
    if (!app.project || !app.project.sequences) {
        throw new Error("Aucune séquence disponible");
    }

    for (var i = 0; i < app.project.sequences.numSequences; i++) {
        var seq = app.project.sequences[i];
        if (seq && seq.name === sequenceName) {
            return seq;
        }
    }
    return null;
};

$._MSBridge.getCategoryOrder = function (catString) {
    if (!catString) {
        return 999;
    }

    var m = String(catString).match(/^CAT=(\d+)_/);
    if (!m) {
        return 999;
    }

    return parseInt(m[1], 10);
};

$._MSBridge.getCategoryBase = function (marker) {
    if (!marker) {
        return "";
    }

    var c = marker.comments ? String(marker.comments) : "";
    if (c.indexOf("CAT=") === 0) {
        return c;
    }

    var n = marker.name ? String(marker.name) : "";
    if (n.indexOf("CAT=") === 0) {
        if (n.indexOf("_START") > -1) {
            return n.replace("_START", "");
        }
        if (n.indexOf("_END") > -1) {
            return n.replace("_END", "");
        }
        return n;
    }

    return "";
};

$._MSBridge.isStartMarker = function (marker) {
    return marker && marker.name && String(marker.name).indexOf("_START") > -1;
};

$._MSBridge.isEndMarker = function (marker) {
    return marker && marker.name && String(marker.name).indexOf("_END") > -1;
};

$._MSBridge.getAllMarkersOrdered = function (sequence) {
    var markers = sequence.markers;
    var arr = [];

    if (!markers || markers.numMarkers === 0) {
        return arr;
    }

    var current = markers.getFirstMarker();
    while (current) {
        arr.push(current);
        current = markers.getNextMarker(current);
    }

    return arr;
};

// 1) On garde la logique simple de paires de marqueurs
$._MSBridge.buildTaggedMarkerPairs = function (sequence) {
    var allMarkers = $._MSBridge.getAllMarkersOrdered(sequence);
    var segments = [];
    var openSegments = {};

    for (var i = 0; i < allMarkers.length; i++) {
        var marker = allMarkers[i];
        var cat = $._MSBridge.getCategoryBase(marker);
        if (!cat) {
            continue;
        }

        if ($._MSBridge.isStartMarker(marker)) {
            openSegments[cat] = marker;
            continue;
        }

        if ($._MSBridge.isEndMarker(marker)) {
            var startMarker = openSegments[cat];
            if (!startMarker) {
                continue;
            }

            var inSec = startMarker.start.seconds;
            var outSec = marker.start.seconds;

            if (outSec > inSec) {
                segments.push({
                    category: cat,
                    order: $._MSBridge.getCategoryOrder(cat),
                    inSec: inSec,
                    outSec: outSec
                });
            }

            openSegments[cat] = null;
        }
    }

    segments.sort(function (a, b) {
        if (a.order !== b.order) {
            return a.order - b.order;
        }
        return a.inSec - b.inSec;
    });

    return segments;
};

// 2) Trouver le clip timeline qui contient entièrement le segment
$._MSBridge.resolveSegmentAgainstReviewTimeline = function (sequence, seg) {
    if (!sequence.videoTracks || sequence.videoTracks.numTracks < 1) {
        return null;
    }

    var track = sequence.videoTracks[0];
    var tolerance = 0.01;

    for (var i = 0; i < track.clips.numItems; i++) {
        var clip = track.clips[i];

        try {
            if (!clip || !clip.projectItem) {
                continue;
            }

            // ignorer logo dans REVIEW_TIMELINE
            if (clip.projectItem.name === "logo.mp4") {
                continue;
            }

            var clipStart = clip.start.seconds;
            var clipEnd = clip.end.seconds;

            if (
                seg.inSec >= (clipStart - tolerance) &&
                seg.outSec <= (clipEnd + tolerance)
            ) {
                var clipSourceIn = 0;

                try {
                    if (clip.inPoint && clip.inPoint.seconds >= 0) {
                        clipSourceIn = clip.inPoint.seconds;
                    }
                } catch (e1) {
                    clipSourceIn = 0;
                }

                var sourceInSec = clipSourceIn + (seg.inSec - clipStart);
                var sourceOutSec = clipSourceIn + (seg.outSec - clipStart);

                return {
                    category: seg.category,
                    order: seg.order,
                    inSec: seg.inSec,
                    outSec: seg.outSec,
                    sourceInSec: sourceInSec,
                    sourceOutSec: sourceOutSec,
                    projectItem: clip.projectItem
                };
            }
        } catch (e2) {
        }
    }

    return null;
};

$._MSBridge.buildResolvedSegments = function (reviewSequence) {
    var rawSegments = $._MSBridge.buildTaggedMarkerPairs(reviewSequence);
    var resolved = [];

    for (var i = 0; i < rawSegments.length; i++) {
        var seg = rawSegments[i];
        var resolvedSeg = $._MSBridge.resolveSegmentAgainstReviewTimeline(reviewSequence, seg);
        if (resolvedSeg) {
            resolved.push(resolvedSeg);
        }
    }

    resolved.sort(function (a, b) {
        if (a.order !== b.order) {
            return a.order - b.order;
        }
        return a.inSec - b.inSec;
    });

    return {
        rawCount: rawSegments.length,
        resolvedCount: resolved.length,
        segments: resolved
    };
};

$._MSBridge.findProjectItemRecursiveByName = function (rootItem, itemName) {
    if (!rootItem) {
        return null;
    }

    if (rootItem.name === itemName) {
        return rootItem;
    }

    if (rootItem.children && rootItem.children.numItems) {
        for (var i = 0; i < rootItem.children.numItems; i++) {
            var found = $._MSBridge.findProjectItemRecursiveByName(rootItem.children[i], itemName);
            if (found) {
                return found;
            }
        }
    }

    return null;
};

$._MSBridge.getLogoItemFromProject = function () {
    return $._MSBridge.findProjectItemRecursiveByName(app.project.rootItem, "logo.mp4");
};

$._MSBridge.clearSequenceTracks = function (sequence) {
    try {
        if (sequence.videoTracks && sequence.videoTracks.numTracks > 0) {
            var vt = sequence.videoTracks[0];
            for (var i = vt.clips.numItems - 1; i >= 0; i--) {
                try { vt.clips[i].remove(0, 1); } catch (e1) {}
            }
        }

        if (sequence.audioTracks && sequence.audioTracks.numTracks > 0) {
            var at = sequence.audioTracks[0];
            for (var j = at.clips.numItems - 1; j >= 0; j--) {
                try { at.clips[j].remove(0, 1); } catch (e2) {}
            }
        }
    } catch (e) {
    }
};

$._MSBridge.placeProjectItemSegment = function (sequence, projectItem, srcInSec, srcOutSec, dstSec) {
    if (!projectItem) {
        return;
    }

    try { projectItem.setInPoint(srcInSec, 4); } catch (e1) {}
    try { projectItem.setOutPoint(srcOutSec, 4); } catch (e2) {}

    try { sequence.videoTracks[0].overwriteClip(projectItem, dstSec); } catch (e3) {}
    try { sequence.audioTracks[0].overwriteClip(projectItem, dstSec); } catch (e4) {}
};

$._MSBridge.buildFinalMainFromMarkers = function () {
    try {
        var reviewSeq = $._MSBridge.findSequenceByName("REVIEW_TIMELINE");
        if (!reviewSeq) {
            throw new Error("REVIEW_TIMELINE introuvable");
        }

        var resolved = $._MSBridge.buildResolvedSegments(reviewSeq);

        if (!resolved.rawCount) {
            return "NO_TAGGED_PAIRS_FOUND";
        }

        if (!resolved.resolvedCount) {
            return "NO_RESOLVED_SEGMENTS | raw_pairs=" + resolved.rawCount;
        }

        var segments = resolved.segments;

        var logoItem = $._MSBridge.getLogoItemFromProject();
        if (!logoItem) {
            throw new Error("logo.mp4 introuvable dans le projet");
        }

        var finalSeqName = "ASSEMBLY_MAIN";
        var finalSeq = $._MSBridge.findSequenceByName(finalSeqName);

        if (!finalSeq) {
            finalSeq = app.project.createNewSequenceFromClips(finalSeqName, [logoItem], app.project.rootItem);
            if (!finalSeq) {
                throw new Error("Impossible de créer ASSEMBLY_MAIN");
            }
        }

        $.sleep(500);
        $._MSBridge.clearSequenceTracks(finalSeq);

        // logo au début
        try { logoItem.clearInPoint(); } catch (e0) {}
        try { logoItem.clearOutPoint(); } catch (e00) {}

        try { finalSeq.videoTracks[0].overwriteClip(logoItem, 0); } catch (e01) {}
        try { finalSeq.audioTracks[0].overwriteClip(logoItem, 0); } catch (e02) {}

        var logoDuration = 5;
        try {
            if (logoItem.duration && logoItem.duration.seconds > 0) {
                logoDuration = logoItem.duration.seconds;
            }
        } catch (e03) {}

        // 6 secondes après le logo avant le premier groupe
        var currentTime = logoDuration + 6;

        var lastOrder = null;
        var groupsCount = 0;

        for (var i = 0; i < segments.length; i++) {
            var seg = segments[i];

            // si on change de catégorie, ajouter 6 secondes entre groupes
            if (lastOrder !== null && seg.order !== lastOrder) {
                currentTime += 6;
                groupsCount += 1;
            }

            $._MSBridge.placeProjectItemSegment(
                finalSeq,
                seg.projectItem,
                seg.sourceInSec,
                seg.sourceOutSec,
                currentTime
            );

            currentTime += (seg.sourceOutSec - seg.sourceInSec);
            lastOrder = seg.order;
        }

        app.project.save();
        
        return "ASSEMBLY_MAIN_BUILT | raw_pairs=" + resolved.rawCount +
                " | resolved_segments=" + resolved.resolvedCount +
                " | grouped_by_category=YES";
    } catch (e) {
        return "ASSEMBLY_MAIN_ERROR: " + e.toString();
    }
};




$._MSBridge.getSequenceMarkersOrdered = function (sequence) {
    var markers = sequence.markers;
    var arr = [];

    if (!markers || markers.numMarkers === 0) {
        return arr;
    }

    var current = markers.getFirstMarker();
    while (current) {
        arr.push(current);
        current = markers.getNextMarker(current);
    }

    return arr;
};

$._MSBridge.markerHasFx = function (marker) {
    if (!marker) {
        return false;
    }

    var c = marker.comments ? String(marker.comments) : "";
    return c.indexOf("FX=") === 0;
};

$._MSBridge.getLastTwoUnstyledMarkersFromAssembly = function () {
    var seq = $._MSBridge.findSequenceByName("ASSEMBLY_MAIN");
    if (!seq) {
        throw new Error("ASSEMBLY_MAIN introuvable");
    }

    var ordered = $._MSBridge.getSequenceMarkersOrdered(seq);
    if (ordered.length < 2) {
        throw new Error("Il faut au moins 2 marqueurs dans ASSEMBLY_MAIN");
    }

    var unstyled = [];
    for (var i = ordered.length - 1; i >= 0; i--) {
        if (!$._MSBridge.markerHasFx(ordered[i])) {
            unstyled.push(ordered[i]);
            if (unstyled.length === 2) {
                break;
            }
        }
    }

    if (unstyled.length < 2) {
        throw new Error("Impossible de trouver 2 marqueurs non stylés dans ASSEMBLY_MAIN");
    }

    var markerA = unstyled[1];
    var markerB = unstyled[0];

    try {
        if (markerA.start.seconds > markerB.start.seconds) {
            var tmp = markerA;
            markerA = markerB;
            markerB = tmp;
        }
    } catch (e) {
    }

    return [markerA, markerB];
};

$._MSBridge.applyStyleToLastTwoMarkersInAssembly = function (styleCode) {
    try {
        var seq = $._MSBridge.findSequenceByName("ASSEMBLY_MAIN");
        if (!seq) {
            throw new Error("ASSEMBLY_MAIN introuvable");
        }

        var pair = $._MSBridge.getLastTwoUnstyledMarkersFromAssembly();
        var startMarker = pair[0];
        var endMarker = pair[1];

        var fx = "FX=" + styleCode;

        startMarker.name = fx + "_START";
        startMarker.comments = fx;

        endMarker.name = fx + "_END";
        endMarker.comments = fx;

        return "OK | " + fx + " | sequence=ASSEMBLY_MAIN";
    } catch (e) {
        return "STYLE_TAG_ERROR: " + e.toString();
    }
};

$._MSBridge.getFxBase = function (marker) {
    if (!marker) {
        return "";
    }

    var c = marker.comments ? String(marker.comments) : "";
    if (c.indexOf("FX=") === 0) {
        return c;
    }

    var n = marker.name ? String(marker.name) : "";
    if (n.indexOf("FX=") === 0) {
        if (n.indexOf("_START") > -1) {
            return n.replace("_START", "");
        }
        if (n.indexOf("_END") > -1) {
            return n.replace("_END", "");
        }
        return n;
    }

    return "";
};

$._MSBridge.fxIsStartMarker = function (marker) {
    return marker && marker.name && String(marker.name).indexOf("FX=") === 0 && String(marker.name).indexOf("_START") > -1;
};

$._MSBridge.fxIsEndMarker = function (marker) {
    return marker && marker.name && String(marker.name).indexOf("FX=") === 0 && String(marker.name).indexOf("_END") > -1;
};

$._MSBridge.buildFxMarkerPairs = function (sequence) {
    var allMarkers = $._MSBridge.getSequenceMarkersOrdered(sequence);
    var segments = [];
    var openSegments = {};

    for (var i = 0; i < allMarkers.length; i++) {
        var marker = allMarkers[i];
        var fx = $._MSBridge.getFxBase(marker);
        if (!fx) {
            continue;
        }

        if ($._MSBridge.fxIsStartMarker(marker)) {
            openSegments[fx] = marker;
            continue;
        }

        if ($._MSBridge.fxIsEndMarker(marker)) {
            var startMarker = openSegments[fx];
            if (!startMarker) {
                continue;
            }

            var inSec = startMarker.start.seconds;
            var outSec = marker.start.seconds;

            if (outSec > inSec) {
                segments.push({
                    fx: fx,
                    inSec: inSec,
                    outSec: outSec
                });
            }

            openSegments[fx] = null;
        }
    }

    segments.sort(function (a, b) {
        return a.inSec - b.inSec;
    });

    return segments;
};

$._MSBridge.findFxForAssemblyClip = function (fxSegments, clipStart, clipEnd) {
    var tolerance = 0.05;

    for (var i = 0; i < fxSegments.length; i++) {
        var fxSeg = fxSegments[i];

        if (
            fxSeg.inSec >= (clipStart - tolerance) &&
            fxSeg.outSec <= (clipEnd + tolerance)
        ) {
            return fxSeg.fx;
        }
    }

    return "";
};

$._MSBridge.findPlacedClipAtTime = function (sequence, trackIndex, dstSec, projectItemName) {
    if (!sequence.videoTracks || sequence.videoTracks.numTracks <= trackIndex) {
        return null;
    }

    var track = sequence.videoTracks[trackIndex];
    var tolerance = 0.08;

    for (var i = track.clips.numItems - 1; i >= 0; i--) {
        var clip = track.clips[i];

        try {
            if (!clip || !clip.projectItem) {
                continue;
            }

            var clipStart = clip.start.seconds;
            if (Math.abs(clipStart - dstSec) <= tolerance) {
                if (!projectItemName || clip.projectItem.name === projectItemName) {
                    return clip;
                }
            }
        } catch (e) {
        }
    }

    return null;
};

$._MSBridge.tryApplySlowMotionToClip = function (trackItem, slowPercent) {
    if (!trackItem) {
        return { ok: false, mode: "NO_TRACK_ITEM" };
    }

    var tried = [];

    try {
        if (typeof trackItem.setSpeed === "function") {
            tried.push("setSpeed");
            trackItem.setSpeed(slowPercent);
            return { ok: true, mode: "setSpeed" };
        }
    } catch (e1) {
        tried.push("setSpeed_failed:" + e1.toString());
    }

    try {
        if (typeof trackItem.setSpeedPercent === "function") {
            tried.push("setSpeedPercent");
            trackItem.setSpeedPercent(slowPercent);
            return { ok: true, mode: "setSpeedPercent" };
        }
    } catch (e2) {
        tried.push("setSpeedPercent_failed:" + e2.toString());
    }

    try {
        if (typeof trackItem.setSpeedAndDuration === "function") {
            tried.push("setSpeedAndDuration");
            trackItem.setSpeedAndDuration(slowPercent, 1);
            return { ok: true, mode: "setSpeedAndDuration" };
        }
    } catch (e3) {
        tried.push("setSpeedAndDuration_failed:" + e3.toString());
    }

    return {
        ok: false,
        mode: "UNSUPPORTED",
        tried: tried.join(" | ")
    };
};

$._MSBridge.openSequenceInTimeline = function (sequence) {
    if (!sequence) {
        return false;
    }

    try {
        if (typeof sequence.openInTimeline === "function") {
            sequence.openInTimeline();
            return true;
        }
    } catch (e1) {
    }

    try {
        if (app.project && typeof app.project.openSequence === "function" && sequence.sequenceID) {
            app.project.openSequence(sequence.sequenceID);
            return true;
        }
    } catch (e2) {
    }

    try {
        if (app.project) {
            app.project.activeSequence = sequence;
            return true;
        }
    } catch (e3) {
    }

    return false;
};

$._MSBridge.addSequenceMarker = function (sequence, startSec, durationSec, name, comments) {
    if (!sequence || !sequence.markers) {
        return false;
    }

    try {
        var marker = sequence.markers.createMarker(startSec);
        if (!marker) {
            return false;
        }

        try { marker.name = name || ""; } catch (e1) {}
        try { marker.comments = comments || ""; } catch (e2) {}

        try {
            if (durationSec && durationSec > 0) {
                marker.end = startSec + durationSec;
            }
        } catch (e3) {}

        return true;
    } catch (e) {
        return false;
    }
};

$._MSBridge.clearFxMarkersFromSequence = function (sequence) {
    if (!sequence || !sequence.markers) {
        return;
    }

    try {
        var toDelete = [];
        var current = sequence.markers.getFirstMarker();

        while (current) {
            var name = current.name ? String(current.name) : "";
            var comments = current.comments ? String(current.comments) : "";

            if (
                name.indexOf("FX_") === 0 ||
                comments.indexOf("FX=") === 0
            ) {
                toDelete.push(current);
            }

            current = sequence.markers.getNextMarker(current);
        }

        for (var i = 0; i < toDelete.length; i++) {
            try { sequence.markers.deleteMarker(toDelete[i]); } catch (e1) {}
        }
    } catch (e) {
    }
};

$._MSBridge.getClipSourceBounds = function (clip) {
    var sourceInSec = 0;
    var sourceOutSec = 0;
    var clipStart = 0;
    var clipEnd = 0;

    try { clipStart = clip.start.seconds; } catch (e1) { clipStart = 0; }
    try { clipEnd = clip.end.seconds; } catch (e2) { clipEnd = clipStart; }

    try { sourceInSec = clip.inPoint.seconds; } catch (e3) { sourceInSec = 0; }

    try {
        sourceOutSec = clip.outPoint.seconds;
    } catch (e4) {
        sourceOutSec = sourceInSec + (clipEnd - clipStart);
    }

    return {
        clipStart: clipStart,
        clipEnd: clipEnd,
        sourceInSec: sourceInSec,
        sourceOutSec: sourceOutSec,
        durationSec: clipEnd - clipStart
    };
};

$._MSBridge.placeSegmentAndReturnEnd = function (sequence, projectItem, srcInSec, srcOutSec, dstSec) {
    $._MSBridge.placeProjectItemSegment(sequence, projectItem, srcInSec, srcOutSec, dstSec);
    return dstSec + (srcOutSec - srcInSec);
};

$._MSBridge.addFxWorkMarkersForSlowmo = function (sequence, startSec, durationSec) {
    $._MSBridge.addSequenceMarker(sequence, startSec, durationSec, "FX_SLOWMO", "FX=SLOWMO");
};

$._MSBridge.addFxWorkMarkersForReverse = function (sequence, startSec, durationSec) {
    $._MSBridge.addSequenceMarker(sequence, startSec, durationSec, "FX_REVERSE", "FX=REVERSE");
};

$._MSBridge.addFxWorkMarkersForReverseSlowmo = function (sequence, startSec, durationSec) {
    $._MSBridge.addSequenceMarker(sequence, startSec, durationSec, "FX_REVERSE_SLOWMO", "FX=REVERSE_SLOWMO");
};



$._MSBridge.getManualGapForSlowmo = function (segmentDurationSec, slowPercent) {
    if (!segmentDurationSec || segmentDurationSec <= 0) {
        return 0;
    }

    if (!slowPercent || slowPercent <= 0) {
        return 0;
    }

    var targetDuration = segmentDurationSec / (slowPercent / 100.0);
    return targetDuration - segmentDurationSec;
};


$._MSBridge.findCategoryForAssemblyClip = function (reviewResolvedSegments, assemblyClip, assemblyClipSourceIn, assemblyClipSourceOut) {
    if (!reviewResolvedSegments || !reviewResolvedSegments.length) {
        return "";
    }

    var tolerance = 0.05;

    for (var i = 0; i < reviewResolvedSegments.length; i++) {
        var seg = reviewResolvedSegments[i];

        try {
            if (!seg.projectItem || !assemblyClip.projectItem) {
                continue;
            }

            var sameItem =
                (seg.projectItem.nodeId && assemblyClip.projectItem.nodeId && seg.projectItem.nodeId === assemblyClip.projectItem.nodeId) ||
                (seg.projectItem.name === assemblyClip.projectItem.name);

            if (!sameItem) {
                continue;
            }

            if (
                Math.abs(seg.sourceInSec - assemblyClipSourceIn) <= tolerance &&
                Math.abs(seg.sourceOutSec - assemblyClipSourceOut) <= tolerance
            ) {
                return seg.category || "";
            }
        } catch (e) {
        }
    }

    return "";
};

$._MSBridge.getAssemblyClipCategoryAtIndex = function (assemblyTrack, clipIndex, reviewResolved) {
    if (!assemblyTrack || clipIndex < 0 || clipIndex >= assemblyTrack.clips.numItems) {
        return "";
    }

    var clip = assemblyTrack.clips[clipIndex];
    if (!clip || !clip.projectItem) {
        return "";
    }

    var clipStart = 0;
    var clipEnd = 0;
    var clipDuration = 0;
    var sourceInSec = 0;
    var sourceOutSec = 0;

    try { clipStart = clip.start.seconds; } catch (e1) { clipStart = 0; }
    try { clipEnd = clip.end.seconds; } catch (e2) { clipEnd = clipStart; }

    clipDuration = clipEnd - clipStart;

    try { sourceInSec = clip.inPoint.seconds; } catch (e3) { sourceInSec = 0; }
    try { sourceOutSec = clip.outPoint.seconds; } catch (e4) { sourceOutSec = sourceInSec + clipDuration; }

    return $._MSBridge.findCategoryForAssemblyClip(
        reviewResolved,
        clip,
        sourceInSec,
        sourceOutSec
    );
};
$._MSBridge.copyAssemblyToStyledMain = function () {
    try {
        var assemblySeq = $._MSBridge.findSequenceByName("ASSEMBLY_MAIN");
        if (!assemblySeq) {
            throw new Error("ASSEMBLY_MAIN introuvable");
        }

        var reviewSeq = $._MSBridge.findSequenceByName("REVIEW_TIMELINE");
        if (!reviewSeq) {
            throw new Error("REVIEW_TIMELINE introuvable");
        }

        var reviewResolved = $._MSBridge.buildResolvedSegments(reviewSeq).segments;

        var logoItem = $._MSBridge.getLogoItemFromProject();
        if (!logoItem) {
            throw new Error("logo.mp4 introuvable dans le projet");
        }

        var styledSeqName = "STYLED_MAIN";
        var styledSeq = $._MSBridge.findSequenceByName(styledSeqName);

        if (!styledSeq) {
            styledSeq = app.project.createNewSequenceFromClips(styledSeqName, [logoItem], app.project.rootItem);
            if (!styledSeq) {
                throw new Error("Impossible de créer STYLED_MAIN");
            }
        }

        $.sleep(500);
        $._MSBridge.clearSequenceTracks(styledSeq);
        $._MSBridge.clearFxMarkersFromSequence(styledSeq);

        if (!assemblySeq.videoTracks || assemblySeq.videoTracks.numTracks < 1) {
            throw new Error("ASSEMBLY_MAIN sans piste vidéo");
        }

        var assemblyTrack = assemblySeq.videoTracks[0];
        var fxSegments = $._MSBridge.buildFxMarkerPairs(assemblySeq);

        var copiedClips = 0;
        var slowmoExpanded = 0;
        var reverseExpanded = 0;
        var closeupGapCount = 0;

        var currentTime = 0;
        var slowPercent = 70;
        var closeupGapSec = 6.0;

        for (var i = 0; i < assemblyTrack.clips.numItems; i++) {
            var clip = assemblyTrack.clips[i];

            try {
                if (!clip || !clip.projectItem) {
                    continue;
                }

                var clipStart = clip.start.seconds;
                var clipEnd = clip.end.seconds;
                var clipDuration = clipEnd - clipStart;

                var sourceInSec = 0;
                var sourceOutSec = 0;

                try {
                    sourceInSec = clip.inPoint.seconds;
                } catch (e1) {
                    sourceInSec = 0;
                }

                try {
                    sourceOutSec = clip.outPoint.seconds;
                } catch (e2) {
                    sourceOutSec = sourceInSec + clipDuration;
                }

                var clipCategory = $._MSBridge.findCategoryForAssemblyClip(
                    reviewResolved,
                    clip,
                    sourceInSec,
                    sourceOutSec
                );

                var isCloseup = (clipCategory.indexOf("CAT=0_") === 0);

                var nextCategory = $._MSBridge.getAssemblyClipCategoryAtIndex(
                    assemblyTrack,
                    i + 1,
                    reviewResolved
                );

                var nextIsCloseup = (nextCategory.indexOf("CAT=0_") === 0);
                var isEndOfCloseupBlock = isCloseup && !nextIsCloseup;

                // Chercher un FX contenu dans ce clip
                var matchedFxSeg = null;
                var tolerance = 0.05;

                for (var j = 0; j < fxSegments.length; j++) {
                    var fxSeg = fxSegments[j];

                    if (
                        fxSeg.inSec >= (clipStart - tolerance) &&
                        fxSeg.outSec <= (clipEnd + tolerance)
                    ) {
                        matchedFxSeg = fxSeg;
                        break;
                    }
                }

                // Aucun FX => copie entière compacte
                if (!matchedFxSeg) {
                    $._MSBridge.placeProjectItemSegment(
                        styledSeq,
                        clip.projectItem,
                        sourceInSec,
                        sourceOutSec,
                        currentTime
                    );

                    currentTime += (sourceOutSec - sourceInSec);
                    copiedClips += 1;

                    if (isEndOfCloseupBlock) {
                        currentTime += closeupGapSec;
                        closeupGapCount += 1;
                    }

                    continue;
                }

                // Clip avec FX
                var segOffsetIn = matchedFxSeg.inSec - clipStart;
                var segOffsetOut = matchedFxSeg.outSec - clipStart;

                var fxSourceIn = sourceInSec + segOffsetIn;
                var fxSourceOut = sourceInSec + segOffsetOut;
                var fxDuration = fxSourceOut - fxSourceIn;

                var normalPart1SourceIn = sourceInSec;
                var normalPart1SourceOut = sourceInSec + segOffsetOut;

                var normalPart2SourceIn = sourceInSec + segOffsetOut;
                var normalPart2SourceOut = sourceOutSec;
                var normalPart2Duration = normalPart2SourceOut - normalPart2SourceIn;

                var manualGapSec = $._MSBridge.getManualGapForSlowmo(fxDuration, slowPercent);

                // 1) début clip normal -> endMark
                $._MSBridge.placeProjectItemSegment(
                    styledSeq,
                    clip.projectItem,
                    normalPart1SourceIn,
                    normalPart1SourceOut,
                    currentTime
                );

                copiedClips += 1;
                currentTime += (normalPart1SourceOut - normalPart1SourceIn);

                if (matchedFxSeg.fx === "FX=SLOWMO") {
                    var slowStart = currentTime;

                    // 2) copie portion marquée
                    $._MSBridge.placeProjectItemSegment(
                        styledSeq,
                        clip.projectItem,
                        fxSourceIn,
                        fxSourceOut,
                        currentTime
                    );

                    $._MSBridge.addFxWorkMarkersForSlowmo(
                        styledSeq,
                        slowStart,
                        fxDuration
                    );

                    currentTime += fxDuration;

                    // 3) vide manuel dynamique
                    currentTime += manualGapSec;

                    // 4) fin clip normal après endMark
                    if (normalPart2Duration > 0.01) {
                        $._MSBridge.placeProjectItemSegment(
                            styledSeq,
                            clip.projectItem,
                            normalPart2SourceIn,
                            normalPart2SourceOut,
                            currentTime
                        );
                        currentTime += normalPart2Duration;
                    }

                    slowmoExpanded += 1;

                } else if (matchedFxSeg.fx === "FX=REVERSE") {
                    var reverseStart = currentTime;

                    // 2) copie reverse
                    $._MSBridge.placeProjectItemSegment(
                        styledSeq,
                        clip.projectItem,
                        fxSourceIn,
                        fxSourceOut,
                        currentTime
                    );

                    $._MSBridge.addFxWorkMarkersForReverse(
                        styledSeq,
                        reverseStart,
                        fxDuration
                    );

                    currentTime += fxDuration;

                    // 3) copie reverse slowmo
                    var reverseSlowStart = currentTime;

                    $._MSBridge.placeProjectItemSegment(
                        styledSeq,
                        clip.projectItem,
                        fxSourceIn,
                        fxSourceOut,
                        currentTime
                    );

                    $._MSBridge.addFxWorkMarkersForReverseSlowmo(
                        styledSeq,
                        reverseSlowStart,
                        fxDuration
                    );

                    currentTime += fxDuration;

                    // 4) vide manuel dynamique
                    currentTime += manualGapSec;

                    // 5) fin clip normal après endMark
                    if (normalPart2Duration > 0.01) {
                        $._MSBridge.placeProjectItemSegment(
                            styledSeq,
                            clip.projectItem,
                            normalPart2SourceIn,
                            normalPart2SourceOut,
                            currentTime
                        );
                        currentTime += normalPart2Duration;
                    }

                    reverseExpanded += 1;

                } else {
                    $._MSBridge.placeProjectItemSegment(
                        styledSeq,
                        clip.projectItem,
                        sourceInSec,
                        sourceOutSec,
                        currentTime
                    );
                    currentTime += (sourceOutSec - sourceInSec);
                }

                // Ajouter 6s seulement à la fin d'un bloc CLOSEUP
                if (isEndOfCloseupBlock) {
                    currentTime += closeupGapSec;
                    closeupGapCount += 1;
                }

            } catch (clipErr) {
            }
        }

        var opened = $._MSBridge.openSequenceInTimeline(styledSeq);

        app.project.save();

        return "STYLED_MAIN_BUILT" +
               " | source=ASSEMBLY_MAIN" +
               " | removed_assembly_gaps=YES" +
               " | kept_manual_gaps_only=YES" +
               " | slow_percent=" + slowPercent +
               " | closeup_gap_sec=" + closeupGapSec +
               " | closeup_gap_count=" + closeupGapCount +
               " | copied_clips=" + copiedClips +
               " | slowmo_expanded=" + slowmoExpanded +
               " | reverse_expanded=" + reverseExpanded +
               " | opened_in_timeline=" + (opened ? "YES" : "NO");
    } catch (e) {
        return "STYLED_MAIN_ERROR: " + e.toString();
    }
};








$._MSBridge.pathExists = function (path) {
    try {
        var f = new File(path);
        if (f.exists) {
            return true;
        }

        var d = new Folder(path);
        return d.exists;
    } catch (e) {
        return false;
    }
};

$._MSBridge.findOrCreateBinRecursive = function (binName) {
    return $._MSBridge.findOrCreateBin(binName);
};

$._MSBridge.importFileToBinIfNeeded = function (filePath, bin) {
    if (!filePath) {
        return null;
    }

    var f = new File(filePath);
    if (!f.exists) {
        return null;
    }

    var existing = $._MSBridge.findProjectItemByName(bin, f.name);
    if (existing) {
        return existing;
    }

    app.project.importFiles([filePath], 1, bin, 0);
    return $._MSBridge.findProjectItemByName(bin, f.name);
};

$._MSBridge.listAudioFilesInFolder = function (folderPath) {
    var folder = new Folder(folderPath);
    if (!folder.exists) {
        return [];
    }

    var files = folder.getFiles();
    var result = [];

    for (var i = 0; i < files.length; i++) {
        var item = files[i];
        if (!(item instanceof File)) {
            continue;
        }

        var name = item.name ? item.name.toLowerCase() : "";
        if (
            name.match(/\.(mp3|wav|aif|aiff|m4a)$/)
        ) {
            result.push(item.fsName);
        }
    }

    return result;
};

$._MSBridge.shuffleArray = function (arr) {
    for (var i = arr.length - 1; i > 0; i--) {
        var j = Math.floor(Math.random() * (i + 1));
        var tmp = arr[i];
        arr[i] = arr[j];
        arr[j] = tmp;
    }
    return arr;
};

$._MSBridge.getSequenceEndSeconds = function (sequence) {
    var maxEnd = 0;
    var i, clip, track;

    try {
        if (sequence.videoTracks) {
            for (i = 0; i < sequence.videoTracks.numTracks; i++) {
                track = sequence.videoTracks[i];
                for (var j = 0; j < track.clips.numItems; j++) {
                    clip = track.clips[j];
                    try {
                        if (clip.end.seconds > maxEnd) {
                            maxEnd = clip.end.seconds;
                        }
                    } catch (e1) {
                    }
                }
            }
        }
    } catch (e2) {
    }

    try {
        if (sequence.audioTracks) {
            for (i = 0; i < sequence.audioTracks.numTracks; i++) {
                track = sequence.audioTracks[i];
                for (var k = 0; k < track.clips.numItems; k++) {
                    clip = track.clips[k];
                    try {
                        if (clip.end.seconds > maxEnd) {
                            maxEnd = clip.end.seconds;
                        }
                    } catch (e3) {
                    }
                }
            }
        }
    } catch (e4) {
    }

    return maxEnd;
};

$._MSBridge.copyTrackItemsToSequence = function (srcTrack, dstTrack, timeOffsetSec) {
    if (!srcTrack || !dstTrack) {
        return;
    }

    for (var i = 0; i < srcTrack.clips.numItems; i++) {
        var clip = srcTrack.clips[i];
        try {
            if (!clip || !clip.projectItem) {
                continue;
            }

            var srcIn = 0;
            var srcOut = 0;
            var dstStart = 0;

            try { srcIn = clip.inPoint.seconds; } catch (e1) { srcIn = 0; }
            try { srcOut = clip.outPoint.seconds; } catch (e2) { srcOut = srcIn + (clip.end.seconds - clip.start.seconds); }

            dstStart = clip.start.seconds + timeOffsetSec;

            try { clip.projectItem.setInPoint(srcIn, 4); } catch (e3) {}
            try { clip.projectItem.setOutPoint(srcOut, 4); } catch (e4) {}

            try { dstTrack.overwriteClip(clip.projectItem, dstStart); } catch (e5) {}
        } catch (e6) {
        }
    }
};

$._MSBridge.collectProjectItemsFromBin = function (bin) {
    var items = [];
    if (!bin || !bin.children) {
        return items;
    }

    for (var i = 0; i < bin.children.numItems; i++) {
        var item = bin.children[i];
        if (item && item.type === 1) {
            items.push(item);
        }
    }

    return items;
};


$._MSBridge.buildCompletedMainFromStyled = function () {
    try {
        var styledSeq = $._MSBridge.findSequenceByName("STYLED_MAIN");
        if (!styledSeq) {
            throw new Error("STYLED_MAIN introuvable");
        }

        var currentCommandPath = "D:/Django_Projects/ms_football_gest/gestion_joueurs/premiere_bridge/current_command.txt";
        var commandPath = $._MSBridge.readTextFile(currentCommandPath).replace(/^\s+|\s+$/g, "");
        var commandText = $._MSBridge.readTextFile(commandPath);
        var command = $._MSBridge.parseJsonText(commandText);
        var jobText = $._MSBridge.readTextFile(command.job_file);
        var job = $._MSBridge.parseJsonText(jobText);

        var graphicsBin = $._MSBridge.findOrCreateBinRecursive(job.graphics_bin_name || "04_GRAPHICS");
        var audioBin = $._MSBridge.findOrCreateBinRecursive(job.audio_bin_name || "05_AUDIO");

        var introItem = null;
        if (job.player_intro_path) {
            var introFile = new File(job.player_intro_path);
            introItem = $._MSBridge.findProjectItemByName(graphicsBin, introFile.name);

            if (!introItem && introFile.exists) {
                try {
                    app.project.importFiles([job.player_intro_path], 1, graphicsBin, 0);
                } catch (introImportErr) {}
                introItem = $._MSBridge.findProjectItemByName(graphicsBin, introFile.name);
            }
        }

        var completedSeqName = "COMPLETED_MAIN";
        var seedItem = $._MSBridge.getLogoItemFromProject() || introItem;
        if (!seedItem) {
            throw new Error("Aucun media seed trouvé pour créer COMPLETED_MAIN");
        }

        var completedSeq = $._MSBridge.findSequenceByName(completedSeqName);
        if (!completedSeq) {
            completedSeq = app.project.createNewSequenceFromClips(completedSeqName, [seedItem], app.project.rootItem);
            if (!completedSeq) {
                throw new Error("Impossible de créer COMPLETED_MAIN");
            }
        }

        $.sleep(500);
        $._MSBridge.clearSequenceTracks(completedSeq);

        var introDuration = 0;
        if (introItem) {
            try {
                if (introItem.duration && introItem.duration.seconds > 0) {
                    introDuration = introItem.duration.seconds;
                }
            } catch (eIntroDur) {
                introDuration = 0;
            }
            if (!introDuration || introDuration <= 0) {
                introDuration = 5.0;
            }
        }

        // détecter le gap réservé à l'intro dans STYLED_MAIN
        var gapFound = false;
        var closeupEnd = 0;
        var nextBlockStart = 0;
        var gapDuration = 0;

        if (styledSeq.videoTracks && styledSeq.videoTracks.numTracks > 0) {
            var vTrack = styledSeq.videoTracks[0];
            for (var gi = 0; gi < vTrack.clips.numItems - 1; gi++) {
                try {
                    var c1 = vTrack.clips[gi];
                    var c2 = vTrack.clips[gi + 1];
                    if (!c1 || !c2) {
                        continue;
                    }

                    var c1End = c1.end.seconds;
                    var c2Start = c2.start.seconds;
                    var g = c2Start - c1End;

                    if (g > 4.5) {
                        gapFound = true;
                        closeupEnd = c1End;
                        nextBlockStart = c2Start;
                        gapDuration = g;
                        break;
                    }
                } catch (gapErr) {}
            }
        }

        var introStart = closeupEnd;
        var introEnd = introStart + introDuration;

        function mapStart(oldStart) {
            if (!gapFound) {
                return oldStart;
            }

            // avant le gap : inchangé
            if (oldStart < nextBlockStart - 0.01) {
                return oldStart;
            }

            // après le gap :
            // on supprime le gap 6s et on réserve la place réelle de l'intro
            return oldStart - gapDuration + introDuration;
        }

        function copyTrackMapped(srcTrack, dstTrack) {
            if (!srcTrack || !dstTrack) {
                return;
            }

            for (var i = 0; i < srcTrack.clips.numItems; i++) {
                var clip = srcTrack.clips[i];
                try {
                    if (!clip || !clip.projectItem) {
                        continue;
                    }

                    var srcIn = 0;
                    var srcOut = 0;
                    var oldStart = 0;
                    var newStart = 0;

                    try { srcIn = clip.inPoint.seconds; } catch (e1) { srcIn = 0; }
                    try { srcOut = clip.outPoint.seconds; } catch (e2) { srcOut = srcIn + (clip.end.seconds - clip.start.seconds); }
                    try { oldStart = clip.start.seconds; } catch (e3) { oldStart = 0; }

                    newStart = mapStart(oldStart);

                    try { clip.projectItem.setInPoint(srcIn, 4); } catch (e4) {}
                    try { clip.projectItem.setOutPoint(srcOut, 4); } catch (e5) {}
                    try { dstTrack.overwriteClip(clip.projectItem, newStart); } catch (e6) {}
                } catch (copyErr) {}
            }
        }

        // 1) recopier toute la VIDEO avec positions finales directes
        if (styledSeq.videoTracks && styledSeq.videoTracks.numTracks > 0 &&
            completedSeq.videoTracks && completedSeq.videoTracks.numTracks > 0) {
            copyTrackMapped(styledSeq.videoTracks[0], completedSeq.videoTracks[0]);
        }

        // 2) nettoyer A1 après copie vidéo
        if (completedSeq.audioTracks && completedSeq.audioTracks.numTracks > 0) {
            var completedA1Clean = completedSeq.audioTracks[0];
            for (var ac = completedA1Clean.clips.numItems - 1; ac >= 0; ac--) {
                try { completedA1Clean.clips[ac].remove(0, 1); } catch (removeErr) {}
            }
        }

        // 3) recopier seulement l'audio restant de STYLED_MAIN avec les mêmes positions finales
        if (styledSeq.audioTracks && styledSeq.audioTracks.numTracks > 0 &&
            completedSeq.audioTracks && completedSeq.audioTracks.numTracks > 0) {
            copyTrackMapped(styledSeq.audioTracks[0], completedSeq.audioTracks[0]);
        }

        // 4) poser l'intro dans l'espace réservé
        if (introItem && gapFound) {
            try { introItem.clearInPoint(); } catch (e0) {}
            try { introItem.clearOutPoint(); } catch (e00) {}

            try {
                if (completedSeq.videoTracks && completedSeq.videoTracks.numTracks > 0) {
                    completedSeq.videoTracks[0].overwriteClip(introItem, introStart);
                }
            } catch (e01) {}

            try {
                if (completedSeq.audioTracks && completedSeq.audioTracks.numTracks > 0) {
                    completedSeq.audioTracks[0].overwriteClip(introItem, introStart);
                }
            } catch (e02) {}

            // relire la vraie fin si possible
            try {
                var cv = completedSeq.videoTracks[0];
                for (var iv = 0; iv < cv.clips.numItems; iv++) {
                    var placedIntro = cv.clips[iv];
                    if (placedIntro &&
                        placedIntro.projectItem &&
                        placedIntro.projectItem.name === introItem.name &&
                        Math.abs(placedIntro.start.seconds - introStart) < 0.1) {
                        introEnd = placedIntro.end.seconds;
                        break;
                    }
                }
            } catch (e03) {}
        }

        // 5) calculer la vraie fin utile
        var usefulEnd = 0;

        try {
            if (completedSeq.videoTracks && completedSeq.videoTracks.numTracks > 0) {
                var vv0 = completedSeq.videoTracks[0];
                for (var vi = 0; vi < vv0.clips.numItems; vi++) {
                    try {
                        if (vv0.clips[vi] && vv0.clips[vi].end.seconds > usefulEnd) {
                            usefulEnd = vv0.clips[vi].end.seconds;
                        }
                    } catch (eV) {}
                }
            }
        } catch (eV2) {}

        try {
            if (completedSeq.audioTracks && completedSeq.audioTracks.numTracks > 0) {
                var aa0 = completedSeq.audioTracks[0];
                for (var ai = 0; ai < aa0.clips.numItems; ai++) {
                    try {
                        if (aa0.clips[ai] && aa0.clips[ai].end.seconds > usefulEnd) {
                            usefulEnd = aa0.clips[ai].end.seconds;
                        }
                    } catch (eA) {}
                }
            }
        } catch (eA2) {}

        // 6) start musique = fin audio logo sur A1
        var logoAudioEnd = 0;
        if (completedSeq.audioTracks && completedSeq.audioTracks.numTracks > 0) {
            var a1ForLogo = completedSeq.audioTracks[0];
            for (var la = 0; la < a1ForLogo.clips.numItems; la++) {
                try {
                    var logoClip = a1ForLogo.clips[la];
                    if (logoClip && logoClip.projectItem && logoClip.projectItem.name === "logo.mp4") {
                        if (logoClip.end.seconds > logoAudioEnd) {
                            logoAudioEnd = logoClip.end.seconds;
                        }
                    }
                } catch (logoErr) {}
            }
        }

        // nettoyer A2
        if (completedSeq.audioTracks && completedSeq.audioTracks.numTracks > 1) {
            var completedA2Clean = completedSeq.audioTracks[1];
            for (var mc = completedA2Clean.clips.numItems - 1; mc >= 0; mc--) {
                try { completedA2Clean.clips[mc].remove(0, 1); } catch (removeMusicErr) {}
            }
        }

        // 7) musique
        var musicItems = $._MSBridge.collectProjectItemsFromBin(audioBin);
        musicItems = $._MSBridge.shuffleArray(musicItems);

        var musicStart = logoAudioEnd;
        var musicPlacedCount = 0;

        // 8) placer la musique jusqu'à usefulEnd exactement
        if (completedSeq.audioTracks && completedSeq.audioTracks.numTracks > 1 && musicItems.length > 0) {
            var musicTrack = completedSeq.audioTracks[1];
            var guard = 0;
            var musicIndex = 0;

            while (musicStart < usefulEnd && guard < 100) {
                if (musicIndex >= musicItems.length) {
                    musicItems = $._MSBridge.shuffleArray(musicItems);
                    musicIndex = 0;
                }

                var musicItem = musicItems[musicIndex];
                if (musicItem) {
                    var remainingDuration = usefulEnd - musicStart;
                    var musicDuration = 0;

                    try {
                        if (musicItem.duration && musicItem.duration.seconds > 0) {
                            musicDuration = musicItem.duration.seconds;
                        }
                    } catch (e0m) {
                        musicDuration = 0;
                    }

                    if (remainingDuration <= 0) {
                        break;
                    }

                    try { musicItem.setInPoint(0, 4); } catch (e1) {}

                    if (musicDuration > 0 && musicDuration > remainingDuration) {
                        try {
                            musicItem.setOutPoint(remainingDuration, 4);
                        } catch (e2) {
                            try { musicItem.clearOutPoint(); } catch (e22) {}
                        }
                    } else {
                        try {
                            if (musicDuration > 0) {
                                musicItem.setOutPoint(musicDuration, 4);
                            } else {
                                musicItem.clearOutPoint();
                            }
                        } catch (e3) {
                            try { musicItem.clearOutPoint(); } catch (e33) {}
                        }
                    }

                    lastMusicStart = musicStart;
                    try { musicTrack.overwriteClip(musicItem, musicStart); } catch (e4) {}
                    lastMusicPlaced = musicItem;

                    if (musicDuration > 0 && musicDuration > remainingDuration) {
                        musicStart += remainingDuration;
                    } else if (musicDuration > 0) {
                        musicStart += musicDuration;
                    } else {
                        musicStart += remainingDuration;
                    }

                    musicPlacedCount += 1;
                }

                musicIndex += 1;
                guard += 1;
            }

            // sécurité : si le dernier clip musique dépasse encore usefulEnd, on le remplace trimé exactement
            try {
                var mt = completedSeq.audioTracks[1];
                for (var mm = mt.clips.numItems - 1; mm >= 0; mm--) {
                    var mclip = mt.clips[mm];
                    if (mclip && mclip.end.seconds > usefulEnd + 0.01) {
                        var mItem = mclip.projectItem;
                        var mStart = mclip.start.seconds;
                        var remain = usefulEnd - mStart;

                        try { mclip.remove(0, 1); } catch (e51) {}

                        if (mItem && remain > 0.01) {
                            try { mItem.setInPoint(0, 4); } catch (e52) {}
                            try { mItem.setOutPoint(remain, 4); } catch (e53) {}
                            try { mt.overwriteClip(mItem, mStart); } catch (e54) {}
                        }
                    }
                }
            } catch (e55) {}
        }

        var opened = $._MSBridge.openSequenceInTimeline(completedSeq);
        app.project.save();

        return "COMPLETED_MAIN_BUILT" +
               " | from=STYLED_MAIN" +
               " | intro_used=" + (introItem ? "YES" : "NO") +
               " | intro_duration=" + introDuration +
               " | closeup_end=" + closeupEnd +
               " | next_block_start=" + nextBlockStart +
               " | intro_start=" + introStart +
               " | intro_end=" + introEnd +
               " | music_start_at_logo_audio_end=" + logoAudioEnd +
               " | music_tracks_placed=" + musicPlacedCount +
               " | useful_end=" + usefulEnd +
               " | opened_in_timeline=" + (opened ? "YES" : "NO");
    } catch (e) {
        return "COMPLETED_MAIN_ERROR: " + e.toString();
    }
};

$._MSBridge.getTrackClips = function (track) {
    var arr = [];
    if (!track || !track.clips) {
        return arr;
    }

    for (var i = 0; i < track.clips.numItems; i++) {
        try {
            if (track.clips[i]) {
                arr.push(track.clips[i]);
            }
        } catch (e) {
        }
    }

    return arr;
};

$._MSBridge.addSequenceRangeMarker = function (sequence, startSec, endSec, name, comments) {
    if (!sequence || !sequence.markers) {
        return false;
    }

    try {
        var marker = sequence.markers.createMarker(startSec);
        if (!marker) {
            return false;
        }

        try { marker.name = name || ""; } catch (e1) {}
        try { marker.comments = comments || ""; } catch (e2) {}

        try {
            if (endSec > startSec) {
                marker.end = endSec;
            }
        } catch (e3) {}

        return true;
    } catch (e) {
        return false;
    }
};

$._MSBridge.clearMarkersByPrefix = function (sequence, prefix) {
    if (!sequence || !sequence.markers) {
        return;
    }

    try {
        var toDelete = [];
        var current = sequence.markers.getFirstMarker();

        while (current) {
            var name = current.name ? String(current.name) : "";
            var comments = current.comments ? String(current.comments) : "";

            if (
                name.indexOf(prefix) === 0 ||
                comments.indexOf(prefix) === 0
            ) {
                toDelete.push(current);
            }

            current = sequence.markers.getNextMarker(current);
        }

        for (var i = 0; i < toDelete.length; i++) {
            try { sequence.markers.deleteMarker(toDelete[i]); } catch (e1) {}
        }
    } catch (e) {
    }
};

$._MSBridge.getTrackEndSeconds = function (track) {
    var maxEnd = 0;
    if (!track || !track.clips) {
        return 0;
    }

    for (var i = 0; i < track.clips.numItems; i++) {
        try {
            var clip = track.clips[i];
            if (clip && clip.end && clip.end.seconds > maxEnd) {
                maxEnd = clip.end.seconds;
            }
        } catch (e) {
        }
    }

    return maxEnd;
};

$._MSBridge.tryApplyAudioGainDbToClip = function (trackItem, gainDb) {
    if (!trackItem) {
        return { ok: false, reason: "NO_TRACK_ITEM" };
    }

    // sécurité simple
    if (typeof gainDb !== "number") {
        return { ok: false, reason: "INVALID_GAIN" };
    }

    // éviter des valeurs absurdes
    if (gainDb > 12) {
        gainDb = 12;
    }
    if (gainDb < -24) {
        gainDb = -24;
    }

    try {
        if (!trackItem.components || trackItem.components.numItems <= 0) {
            return { ok: false, reason: "NO_COMPONENTS" };
        }

        for (var i = 0; i < trackItem.components.numItems; i++) {
            var comp = trackItem.components[i];
            if (!comp || !comp.properties) {
                continue;
            }

            var compName = comp.displayName ? String(comp.displayName).toLowerCase() : "";

            // on cible seulement le vrai composant volume
            var isVolumeComponent =
                compName === "volume" ||
                compName === "niveau" ||
                compName.indexOf("volume") === 0 ||
                compName.indexOf("niveau") === 0;

            if (!isVolumeComponent) {
                continue;
            }

            for (var j = 0; j < comp.properties.numItems; j++) {
                var prop = comp.properties[j];
                if (!prop) {
                    continue;
                }

                var propName = prop.displayName ? String(prop.displayName).toLowerCase() : "";

                // on cible seulement la propriété "Level"
                var isLevelProperty =
                    propName === "level" ||
                    propName === "niveau" ||
                    propName === "level db" ||
                    propName === "niveau db";

                if (!isLevelProperty) {
                    continue;
                }

                try {
                    prop.setValue(gainDb, 1);
                    return {
                        ok: true,
                        mode: "volume_level_property",
                        component: comp.displayName,
                        property: prop.displayName,
                        value: gainDb
                    };
                } catch (e1) {
                    return {
                        ok: false,
                        reason: "SETVALUE_FAILED",
                        component: comp.displayName,
                        property: prop.displayName,
                        error: e1.toString()
                    };
                }
            }
        }
    } catch (e2) {
        return { ok: false, reason: "EXCEPTION", error: e2.toString() };
    }

    return { ok: false, reason: "LEVEL_PROPERTY_NOT_FOUND" };
};