// main.js - shared layout behaviour, loaded on every page as a module (base.html):
// active investigation selector, module history panel, update check, notifications,
// pivots and the HTML-escaping / clipboard helpers other scripts use.
//
// The parts are in static/js/lib/. The other scripts on a page (classic scripts that
// base.html loads deferred after this one, plugin renderers) use these as globals, so
// every one of them is set on window here, in one place.
import {
    appConfirm,
    clickArgs,
    copyTextToClipboard,
    escapeAttr,
    escapeHtml,
    fmtDate,
    fmtDateTime,
    keepLoadedImages,
    pageData,
    refreshIcons,
    registerActions,
    replaceKeepingImages,
    safeUrl,
    showTemporaryNotification,
    timeAgo,
} from './lib/dom.js';
import {
    clearCurrentInvestigation,
    currentInvestigationId,
    investigationMenuItems,
    loadInvestigations,
    logout,
    offerToStopRecording,
    openCreateInvestigationModal,
    selectInvestigation,
} from './lib/investigations.js';
import { closeContextMenu, openContextMenu } from './lib/context_menu.js';
import './lib/header.js';
import {
    ENTITY_LABELS,
    checkExistingResults,
    fetchServiceHistory,
    getModules,
    loadResult,
    moduleBadges,
    showResultSelector,
    showSavedResultFallback,
} from './lib/history.js';
import { jobResultLink, jobStatusHtml, refreshJobs, startJob } from './lib/jobs.js';
import {
    TEXT_IDENTIFIER_RE,
    builtwithTagUrl,
    externalSearchesFor,
    faviconHashTag,
    fofaIconHashUrl,
    getResources,
    identifierGroupsHtml,
    nsLookupSuggestion,
    openPivotMenu,
    pivotChip,
    pivotField,
    pivotInText,
    pivotKeyType,
    pivotLogin,
    pivotText,
    pivotTypeFor,
    trackerTag,
} from './lib/pivots.js';
import { externalSitesHtml, sharedCache } from './lib/identifiers.js';
import { openImageViewer } from './lib/image_viewer.js';
import { LOOKUP_EXAMPLES_HINT, phoneSuggestionsHtml, setupLinkHtml } from './lib/lookup_box.js';

window.escapeHtml = escapeHtml;
window.escapeAttr = escapeAttr;
window.safeUrl = safeUrl;
window.registerActions = registerActions;
window.clickArgs = clickArgs;
window.pageData = pageData;
window.keepLoadedImages = keepLoadedImages;
window.replaceKeepingImages = replaceKeepingImages;
window.refreshIcons = refreshIcons;
window.fmtDateTime = fmtDateTime;
window.fmtDate = fmtDate;
window.timeAgo = timeAgo;
window.copyTextToClipboard = copyTextToClipboard;
window.showTemporaryNotification = showTemporaryNotification;
window.appConfirm = appConfirm;
window.offerToStopRecording = offerToStopRecording;
window.investigationMenuItems = investigationMenuItems;
window.closeContextMenu = closeContextMenu;
window.openContextMenu = openContextMenu;
window.logout = logout;
window.getCurrentInvestigationId = () => currentInvestigationId;
window.openCreateModal = openCreateInvestigationModal;
window.loadInvestigationsDropdown = loadInvestigations;
window.selectInvestigation = selectInvestigation;
window.clearCurrentInvestigation = clearCurrentInvestigation;
window.showSavedResultFallback = showSavedResultFallback;
window.loadResult = loadResult;
window.showResultSelector = showResultSelector;
window.checkExistingResults = checkExistingResults;
window.fetchServiceHistory = fetchServiceHistory;
// Id of the saved result a module response was recorded as (null when not recording).
window.savedResultId = (response) =>
    response && response.headers ? response.headers.get('X-Investigation-Result-ID') : null;
window.ENTITY_LABELS = ENTITY_LABELS;
window.getModules = getModules;
window.moduleBadges = moduleBadges;
window.startJob = startJob;
window.jobResultLink = jobResultLink;
window.jobStatusHtml = jobStatusHtml;
window.refreshJobs = refreshJobs;
window.openPivotMenu = openPivotMenu;
window.getResources = getResources;
// Answers the page already has (the Identifiers tab lists them with each identifier)
window.primeSharedIdentifiers = (entries) => {
    entries.forEach(([name, places]) => sharedCache.set(name, places || []));
};
window.openImageViewer = openImageViewer;
window.setupLinkHtml = setupLinkHtml;
window.phoneSuggestionsHtml = phoneSuggestionsHtml;
window.LOOKUP_EXAMPLES_HINT = LOOKUP_EXAMPLES_HINT;
window.pivotChip = pivotChip;
window.pivotTypeFor = pivotTypeFor;
window.pivotText = pivotText;
window.pivotLogin = pivotLogin;
window.pivotField = pivotField;
window.pivotInText = pivotInText;
window.builtwithTagUrl = builtwithTagUrl;
window.trackerTag = trackerTag;
window.fofaIconHashUrl = fofaIconHashUrl;
window.faviconHashTag = faviconHashTag;
window.identifierGroupsHtml = identifierGroupsHtml;
window.nsLookupSuggestion = nsLookupSuggestion;
// used by other scripts without a window. assignment before (function declarations of a classic script)
window.openCreateInvestigationModal = openCreateInvestigationModal;
window.externalSearchesFor = externalSearchesFor;
window.externalSitesHtml = externalSitesHtml;
window.pivotKeyType = pivotKeyType;
window.TEXT_IDENTIFIER_RE = TEXT_IDENTIFIER_RE;
