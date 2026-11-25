/* Adapted from HaSu Desktop. See SOURCE.md, LICENSE and NOTICE alongside this file. */

(() => {
'use strict';

const normalize = value => value.trim().toLowerCase();

function searchScore(entry, query) {
  const needle = normalize(query);
  if (!needle) return 0;

  const label = normalize(entry.label);
  const context = normalize(entry.context);
  const haystack = normalize([entry.label, entry.context, entry.description ?? '', ...entry.keywords].join(' '));
  const terms = needle.split(/\s+/).filter(Boolean);

  if (!terms.every(term => haystack.includes(term))) return 0;
  if (label === needle) return 100;
  if (label.startsWith(needle)) return 90;
  if (label.includes(needle)) return 80;
  if (context.includes(needle)) return 70;
  if (terms.every(term => label.includes(term) || context.includes(term))) return 60;
  return 50;
}

function filterSettingsSearchEntries(entries, query) {
  return entries
    .map((entry, index) => ({entry, index, score:searchScore(entry, query)}))
    .filter(result => result.score > 0)
    .sort((left, right) => right.score - left.score || left.index - right.index)
    .map(result => result.entry);
}

const MIDDLE_BUTTON = 1;
const isMetaClose = event => event.button === 0 && event.metaKey;
let pressedOn = null;

function wireTabClose(tab, action) {
  tab.addEventListener('mousedown', event => {
    if (event.button === MIDDLE_BUTTON) event.preventDefault();
  });
  tab.addEventListener('pointerdown', event => {
    if (event.button === MIDDLE_BUTTON) pressedOn = event.currentTarget;
  });
  tab.addEventListener('pointerup', event => {
    if (event.button !== MIDDLE_BUTTON) return;
    const armed = pressedOn === event.currentTarget;
    pressedOn = null;
    if (armed) action();
  });
  tab.addEventListener('pointercancel', () => { pressedOn = null; });
  tab.addEventListener('keydown', event => {
    if (event.key !== 'Delete' || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    event.preventDefault();
    action();
  });
}

function treeThumbnail(node, resting) {
  const element = document.createElement('div');
  if (node.type === 'group') {
    element.className = 'thumbnail-pane';
    element.classList.toggle('resting', node.panes.every(id => resting.has(id)));
    return element;
  }

  element.className = 'thumbnail-split';
  element.style.flexDirection = node.orientation === 'row' ? 'row' : 'column';
  node.children.forEach((child, index) => {
    const wrapper = document.createElement('div');
    wrapper.style.flex = String(node.weights[index]) + ' 1 0px';
    wrapper.append(treeThumbnail(child, resting));
    element.append(wrapper);
  });
  return element;
}

window.HasuDesktopPort = Object.freeze({filterSettingsSearchEntries, isMetaClose, wireTabClose, treeThumbnail});
})();
