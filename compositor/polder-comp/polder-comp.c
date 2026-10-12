/* polder-comp (Polder OS Rev 31, fase 1): a small Wayland compositor on wlroots 0.18 (based on tinywl).
 * - xdg-shell + Xwayland windows, keyboard/pointer, focus, move/resize (client requests + Super+drag)
 * - layer-shell (background/bottom/top/overlay) so Polder panels can become gtk-layer-shell surfaces
 * - rounded corners (12 px) + soft shadows with scenefx (GLES, -DPOLDER_SCENEFX); pixman builds get a
 *   stepped rectangular shadow and square corners (pixman has no rounded clipping in wlroots' scene)
 * - Polder palette (POLDER_PALETTE=palette.env) for the background colour
 * - Super tap -> POLDER_LAUNCHER, Super+Return -> POLDER_TERMINAL, Super+Q close, Alt+Tab cycle, Super+Shift+Esc quit
 * - screencopy + xdg-output (grim), virtual keyboard/pointer (wtype, tests), xdg-decoration (client-side) */
#define _POSIX_C_SOURCE 200112L
#include <assert.h>
#include <getopt.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <wayland-server-core.h>
#include <wlr/backend.h>
#include <wlr/backend/headless.h>
#include <wlr/backend/multi.h>
#include <wlr/render/allocator.h>
#include <wlr/render/wlr_renderer.h>
#include <wlr/types/wlr_cursor.h>
#include <wlr/types/wlr_compositor.h>
#include <wlr/types/wlr_data_device.h>
#include <wlr/types/wlr_input_device.h>
#include <wlr/types/wlr_keyboard.h>
#include <wlr/types/wlr_output.h>
#include <wlr/types/wlr_output_layout.h>
#include <wlr/types/wlr_pointer.h>
#include <wlr/types/wlr_seat.h>
#include <wlr/types/wlr_subcompositor.h>
#include <wlr/types/wlr_xcursor_manager.h>
#include <wlr/types/wlr_xdg_shell.h>
#include <wlr/types/wlr_layer_shell_v1.h>
#include <wlr/types/wlr_screencopy_v1.h>
#include <wlr/types/wlr_xdg_output_v1.h>
#include <wlr/types/wlr_virtual_keyboard_v1.h>
#include <wlr/types/wlr_virtual_pointer_v1.h>
#include <wlr/types/wlr_xdg_decoration_v1.h>
#include <wlr/types/wlr_viewporter.h>
#include <wlr/types/wlr_data_control_v1.h>
#include <wlr/types/wlr_primary_selection_v1.h>
#include <wlr/util/log.h>
#include <wlr/xwayland.h>
#include <xkbcommon/xkbcommon.h>
#ifdef POLDER_SCENEFX
#include <scenefx/types/wlr_scene.h>
#include <scenefx/render/fx_renderer/fx_renderer.h>
#else
#include <wlr/types/wlr_scene.h>
#endif

#define RADIUS 12
enum cursor_mode { CUR_PASS, CUR_MOVE, CUR_RESIZE };
enum view_type { VIEW_XDG, VIEW_X11 };

struct server {
	struct wl_display *display;
	struct wlr_backend *backend;
	struct wlr_renderer *renderer;
	struct wlr_allocator *allocator;
	struct wlr_scene *scene;
	struct wlr_scene_output_layout *scene_layout;
	struct wlr_scene_rect *bg;
	struct wlr_scene_tree *layer[4];   /* background, bottom, top, overlay */
	struct wlr_scene_tree *views_tree, *unmanaged_tree;
	struct wlr_compositor *compositor;
	struct wlr_xdg_shell *xdg_shell;
	struct wlr_layer_shell_v1 *layer_shell;
	struct wlr_xwayland *xwayland;
	struct wl_listener new_xdg_toplevel, new_xdg_popup, new_layer_surface, xwl_ready, xwl_new_surface;
	struct wl_list views, layer_surfaces, outputs, keyboards;
	struct wlr_cursor *cursor;
	struct wlr_xcursor_manager *xcursor;
	struct wl_listener cursor_motion, cursor_motion_abs, cursor_button, cursor_axis, cursor_frame;
	struct wlr_seat *seat;
	struct wl_listener new_input, request_cursor, request_set_selection, new_vkbd, new_vptr, new_deco;
	enum cursor_mode mode;
	struct view *grabbed;
	double grab_x, grab_y; struct wlr_box grab_box; uint32_t resize_edges;
	struct wlr_output_layout *output_layout;
	struct wl_listener new_output;
	float bg_color[4];
	bool super_alone;
	const char *launcher, *terminal;
	struct wlr_box usable;   /* output area minus layer-shell exclusive zones */
};

struct output { struct wl_list link; struct server *server; struct wlr_output *wlr; struct wl_listener frame, request_state, destroy; };

struct view {
	struct wl_list link;
	struct server *server;
	enum view_type type;
	struct wlr_xdg_toplevel *xdg;
	struct wlr_xwayland_surface *xs;
	struct wlr_scene_tree *tree, *content;
#ifdef POLDER_SCENEFX
	struct wlr_scene_shadow *shadow;
#else
	struct wlr_scene_rect *shadow[4];
#endif
	bool mapped, placed;
	bool has_target; int tx, ty;   /* desired window-geometry origin; re-applied on commit because CSD geometry changes (GTK drops shadows when tiled) */
	int snap;               /* SNAP_NONE/LEFT/RIGHT/MAX */
	struct wlr_box saved;   /* geometry before snapping */
	struct wl_listener map, unmap, commit, destroy, request_move, request_resize, associate, dissociate, request_configure, request_activate;
};

struct layer { struct wl_list link; struct server *server; struct wlr_layer_surface_v1 *ls; struct wlr_scene_layer_surface_v1 *sls;
	struct wl_listener commit, map, unmap, destroy; };
struct keyboard { struct wl_list link; struct server *server; struct wlr_keyboard *wlr; struct wl_listener modifiers, key, destroy; };

static void spawn(struct server *s, const char *cmd) {
	if (!cmd || !*cmd) return;
	if (fork() == 0) { setsid(); execl("/bin/sh", "/bin/sh", "-c", cmd, (void *)NULL); _exit(127); }
	(void)s;
}

static void read_palette(struct server *s) {
	s->bg_color[0] = 0.973f; s->bg_color[1] = 0.976f; s->bg_color[2] = 0.988f; s->bg_color[3] = 1;   /* #f8f9fc */
	const char *p = getenv("POLDER_PALETTE"); FILE *f = p ? fopen(p, "r") : NULL; char line[256];
	while (f && fgets(line, sizeof line, f)) {
		unsigned r, g, b;
		if (sscanf(line, "SURFACE=#%02x%02x%02x", &r, &g, &b) == 3) { s->bg_color[0] = r / 255.f; s->bg_color[1] = g / 255.f; s->bg_color[2] = b / 255.f; }
	}
	if (f) fclose(f);
	unsigned r, g, b; const char *o = getenv("POLDER_BG");   /* override, e.g. a contrasting colour for corner tests */
	if (o && sscanf(o, "#%02x%02x%02x", &r, &g, &b) == 3) { s->bg_color[0] = r / 255.f; s->bg_color[1] = g / 255.f; s->bg_color[2] = b / 255.f; }
}

/* ---------------- views ---------------- */
static struct wlr_surface *view_surface(struct view *v) { return v->type == VIEW_XDG ? v->xdg->base->surface : v->xs->surface; }
static void view_geometry(struct view *v, struct wlr_box *b) {
	/* wlr_scene_xdg_surface_create already shifts the surface by -geometry, so the view tree's
	 * origin IS the window-geometry origin: report x=y=0 to avoid double offsets (Rev 32 fix) */
	if (v->type == VIEW_XDG) { wlr_xdg_surface_get_geometry(v->xdg->base, b); b->x = 0; b->y = 0; }
	else *b = (struct wlr_box){ 0, 0, v->xs->width, v->xs->height };
}
static void view_activate(struct view *v, bool on) {
	if (v->type == VIEW_XDG) wlr_xdg_toplevel_set_activated(v->xdg, on);
	else { wlr_xwayland_surface_activate(v->xs, on); if (on) wlr_xwayland_surface_restack(v->xs, NULL, XCB_STACK_MODE_ABOVE); }
}

#ifdef POLDER_SCENEFX
static void round_buffer(struct wlr_scene_buffer *buf, int sx, int sy, void *data) {
	(void)sx; (void)sy; (void)data; wlr_scene_buffer_set_corner_radius(buf, RADIUS, CORNER_LOCATION_ALL);
}
#endif

static void view_update_decor(struct view *v) {
	struct wlr_box g; view_geometry(v, &g);
	if (g.width <= 0 || g.height <= 0) return;
#ifdef POLDER_SCENEFX
	/* scenefx: real rounded corners on the surface buffers + gaussian shadow behind */
	wlr_scene_node_for_each_buffer(&v->content->node, round_buffer, NULL);
	int blur = 16;
	wlr_scene_shadow_set_size(v->shadow, g.width + 2 * blur, g.height + 2 * blur);
	wlr_scene_node_set_position(&v->shadow->node, g.x - blur, g.y - blur + 4);
#else
	/* pixman: four stacked translucent rectangles = stepped soft shadow (corners stay square) */
	for (int i = 0; i < 4; i++) {
		int d = (i + 1) * 3;
		wlr_scene_rect_set_size(v->shadow[i], g.width + 2 * d, g.height + 2 * d);
		wlr_scene_node_set_position(&v->shadow[i]->node, g.x - d, g.y - d + 3);
	}
#endif
}

static void view_create_tree(struct view *v) {
	v->tree = wlr_scene_tree_create(v->server->views_tree);
	v->tree->node.data = v;
#ifdef POLDER_SCENEFX
	float c[4] = { 0, 0, 0, 0.35f };
	v->shadow = wlr_scene_shadow_create(v->tree, 1, 1, RADIUS + 6, 12.0f, c);
#else
	for (int i = 3; i >= 0; i--) { float c[4] = { 0, 0, 0, 0.045f }; v->shadow[i] = wlr_scene_rect_create(v->tree, 1, 1, c); }
#endif
}

static void focus_view(struct view *v) {
	if (!v) return;
	struct server *s = v->server; struct wlr_seat *seat = s->seat;
	struct wlr_surface *surf = view_surface(v), *prev = seat->keyboard_state.focused_surface;
	if (!surf) return;
	wlr_scene_node_raise_to_top(&v->tree->node);
	wl_list_remove(&v->link); wl_list_insert(&s->views, &v->link);
	if (prev == surf) return;
	struct view *pv;
	wl_list_for_each(pv, &s->views, link) if (pv != v && pv->mapped && view_surface(pv) == prev) view_activate(pv, false);
	view_activate(v, true);
	struct wlr_keyboard *kb = wlr_seat_get_keyboard(seat);
	/* enter even without a keyboard (e.g. the last virtual keyboard went away): the next one inherits the focus */
	if (kb) wlr_seat_keyboard_notify_enter(seat, surf, kb->keycodes, kb->num_keycodes, &kb->modifiers);
	else wlr_seat_keyboard_notify_enter(seat, surf, NULL, 0, NULL);
}

static struct view *view_at(struct server *s, double lx, double ly, struct wlr_surface **surface, double *sx, double *sy) {
	struct wlr_scene_node *node = wlr_scene_node_at(&s->scene->tree.node, lx, ly, sx, sy);
	if (!node || node->type != WLR_SCENE_NODE_BUFFER) return NULL;
	struct wlr_scene_surface *ss = wlr_scene_surface_try_from_buffer(wlr_scene_buffer_from_node(node));
	if (!ss) return NULL;
	*surface = ss->surface;
	struct wlr_scene_tree *t = node->parent;
	while (t && t->node.data == NULL) t = t->node.parent;
	return t ? t->node.data : NULL;
}

enum { SNAP_NONE, SNAP_LEFT, SNAP_RIGHT, SNAP_MAX };
static void view_box(struct view *v, struct wlr_box *b);
static void view_set_size(struct view *v, int x, int y, int w, int h);
static void begin_grab(struct view *v, enum cursor_mode mode, uint32_t edges) {
	struct server *s = v->server; s->grabbed = v; s->mode = mode;
	if (mode == CUR_MOVE && v->snap != SNAP_NONE) {
		struct wlr_box b; view_box(v, &b); double fx = b.width ? (s->cursor->x - b.x) / b.width : 0.5;
		struct wlr_box sv = v->saved; v->snap = SNAP_NONE;
		if (v->type == VIEW_XDG) { wlr_xdg_toplevel_set_maximized(v->xdg, false); wlr_xdg_toplevel_set_tiled(v->xdg, 0); }
		else wlr_xwayland_surface_set_maximized(v->xs, false);
		view_set_size(v, s->cursor->x - fx * sv.width, b.y, sv.width, sv.height);
	}
	if (mode == CUR_MOVE) { s->grab_x = s->cursor->x - v->tree->node.x; s->grab_y = s->cursor->y - v->tree->node.y; return; }
	struct wlr_box g; view_geometry(v, &g);
	double bx = v->tree->node.x + g.x + ((edges & WLR_EDGE_RIGHT) ? g.width : 0);
	double by = v->tree->node.y + g.y + ((edges & WLR_EDGE_BOTTOM) ? g.height : 0);
	s->grab_x = s->cursor->x - bx; s->grab_y = s->cursor->y - by;
	s->grab_box = g; s->grab_box.x += v->tree->node.x; s->grab_box.y += v->tree->node.y; s->resize_edges = edges;
}

static void view_set_size(struct view *v, int x, int y, int w, int h) {
	if (v->type == VIEW_XDG) {
		struct wlr_box g; view_geometry(v, &g);
		wlr_scene_node_set_position(&v->tree->node, x - g.x, y - g.y); wlr_xdg_toplevel_set_size(v->xdg, w, h);
		v->has_target = true; v->tx = x; v->ty = y;
	} else { wlr_scene_node_set_position(&v->tree->node, x, y); wlr_xwayland_surface_configure(v->xs, x, y, w, h); }
}

#define GAP 8
static void view_box(struct view *v, struct wlr_box *b) {   /* window geometry in layout coords */
	struct wlr_box g; view_geometry(v, &g);
	b->x = v->tree->node.x + g.x; b->y = v->tree->node.y + g.y; b->width = g.width; b->height = g.height;
}
static struct wlr_box usable_area(struct server *s) {
	if (s->usable.width > 0) return s->usable;
	struct wlr_box b = {0, 0, 1366, 768}; struct output *o;
	wl_list_for_each(o, &s->outputs, link) { wlr_output_layout_get_box(s->output_layout, o->wlr, &b); break; }
	return b;
}
static void view_move_to(struct view *v, int x, int y) {
	struct wlr_box g; view_geometry(v, &g);
	if (v->type == VIEW_XDG) { wlr_scene_node_set_position(&v->tree->node, x - g.x, y - g.y); v->has_target = true; v->tx = x; v->ty = y; }
	else { wlr_scene_node_set_position(&v->tree->node, x, y); wlr_xwayland_surface_configure(v->xs, x, y, v->xs->width, v->xs->height); }
}
/* smart placement: centre the first window in the usable area, cascade later ones
 * by 32px whenever the spot is already taken; always keep the window on screen */
static void view_place(struct view *v) {
	struct server *s = v->server; struct wlr_box u = usable_area(s), g; view_geometry(v, &g);
	int w = g.width, h = g.height;
	if (w > u.width - 2 * GAP) w = u.width - 2 * GAP;
	if (h > u.height - 2 * GAP) h = u.height - 2 * GAP;
	if (w != g.width || h != g.height) view_set_size(v, u.x + GAP, u.y + GAP, w, h);
	int x = u.x + (u.width - w) / 2, y = u.y + (u.height - h) / 2;
	for (int tries = 0; tries < 12; tries++) {
		bool taken = false; struct view *o;
		wl_list_for_each(o, &s->views, link) {
			if (o == v || !o->mapped) continue;
			struct wlr_box ob; view_box(o, &ob);
			if (abs(ob.x - x) < 24 && abs(ob.y - y) < 24) { taken = true; break; }
		}
		if (!taken) break;
		x += 32; y += 32;
		if (x + w > u.x + u.width || y + h > u.y + u.height) { x = u.x + GAP + tries * 8; y = u.y + GAP + tries * 8; }
	}
	view_move_to(v, x, y); v->placed = true;
}
static void view_snap(struct view *v, int mode) {
	if (v->snap == SNAP_NONE && mode != SNAP_NONE) view_box(v, &v->saved);
	struct wlr_box u = usable_area(v->server), t;
	switch (mode) {
	case SNAP_LEFT:  t = (struct wlr_box){ u.x + GAP, u.y + GAP, u.width / 2 - GAP - GAP / 2, u.height - 2 * GAP }; break;
	case SNAP_RIGHT: t = (struct wlr_box){ u.x + u.width / 2 + GAP / 2, u.y + GAP, u.width / 2 - GAP - GAP / 2, u.height - 2 * GAP }; break;
	case SNAP_MAX:   t = u; break;
	default: if (v->snap == SNAP_NONE) return; t = v->saved; break;
	}
	if (v->type == VIEW_XDG) {
		wlr_xdg_toplevel_set_maximized(v->xdg, mode == SNAP_MAX);
		wlr_xdg_toplevel_set_tiled(v->xdg, mode == SNAP_LEFT ? (WLR_EDGE_TOP|WLR_EDGE_BOTTOM|WLR_EDGE_RIGHT) :
			mode == SNAP_RIGHT ? (WLR_EDGE_TOP|WLR_EDGE_BOTTOM|WLR_EDGE_LEFT) : mode == SNAP_MAX ? 15 : 0);
	} else wlr_xwayland_surface_set_maximized(v->xs, mode == SNAP_MAX);
	v->snap = mode;
	view_set_size(v, t.x, t.y, t.width, t.height);
	wlr_log(WLR_INFO, "snap %d -> %d,%d %dx%d", mode, t.x, t.y, t.width, t.height);
}

static void view_map(struct wl_listener *l, void *d) {
	struct view *v = wl_container_of(l, v, map); (void)d;
	struct server *s = v->server;
	if (v->type == VIEW_X11) wlr_log(WLR_INFO, "map x11 '%s' %dx%d+%d+%d or=%d", v->xs->title ? v->xs->title : "", v->xs->width, v->xs->height, v->xs->x, v->xs->y, v->xs->override_redirect);
	if (v->type == VIEW_X11) {
		v->content = wlr_scene_subsurface_tree_create(v->tree, v->xs->surface);
		if (v->xs->override_redirect) {   /* menus/tooltips: place exactly, no shadow, no focus steal */
			wlr_scene_node_reparent(&v->tree->node, s->unmanaged_tree);
			wlr_scene_node_set_position(&v->tree->node, v->xs->x, v->xs->y); v->mapped = true; return;
		}
		wlr_scene_node_set_position(&v->tree->node, v->xs->x, v->xs->y);
	}
	v->mapped = true; wlr_scene_node_set_enabled(&v->tree->node, true);
	if (!v->placed && (v->type == VIEW_XDG || (v->xs->x == 0 && v->xs->y == 0))) view_place(v);
	wl_list_insert(&s->views, &v->link);
	view_update_decor(v); focus_view(v);
}
static void view_unmap(struct wl_listener *l, void *d) {
	struct view *v = wl_container_of(l, v, unmap); (void)d;
	if (v == v->server->grabbed) { v->server->mode = CUR_PASS; v->server->grabbed = NULL; }
	if (v->type == VIEW_X11 && v->content) { wlr_scene_node_destroy(&v->content->node); v->content = NULL; }
	if (v->mapped && !(v->type == VIEW_X11 && v->xs->override_redirect)) wl_list_remove(&v->link);
	v->mapped = false;
	if (!wl_list_empty(&v->server->views)) { struct view *n = wl_container_of(v->server->views.next, n, link); focus_view(n); }
}
static void view_commit(struct wl_listener *l, void *d) {
	struct view *v = wl_container_of(l, v, commit); (void)d;
	if (v->type == VIEW_XDG && v->xdg->base->initial_commit) {
		wlr_xdg_toplevel_set_size(v->xdg, 0, 0);
		return;
	}
	if (v->mapped && v->type == VIEW_XDG && v->has_target) {
		struct wlr_box g; view_geometry(v, &g);
		wlr_scene_node_set_position(&v->tree->node, v->tx - g.x, v->ty - g.y);
	}
	if (v->mapped) view_update_decor(v);
}
static void view_request_move(struct wl_listener *l, void *d) { struct view *v = wl_container_of(l, v, request_move); (void)d; begin_grab(v, CUR_MOVE, 0); }
static void view_request_resize(struct wl_listener *l, void *d) {
	struct view *v = wl_container_of(l, v, request_resize);
	uint32_t edges = v->type == VIEW_XDG ? ((struct wlr_xdg_toplevel_resize_event *)d)->edges : ((struct wlr_xwayland_resize_event *)d)->edges;
	begin_grab(v, CUR_RESIZE, edges);
}
static void view_destroy(struct wl_listener *l, void *d) {
	struct view *v = wl_container_of(l, v, destroy); (void)d;
	wl_list_remove(&v->destroy.link); wl_list_remove(&v->request_move.link); wl_list_remove(&v->request_resize.link);
	if (v->type == VIEW_XDG) { wl_list_remove(&v->map.link); wl_list_remove(&v->unmap.link); wl_list_remove(&v->commit.link); }
	else { wl_list_remove(&v->associate.link); wl_list_remove(&v->dissociate.link); wl_list_remove(&v->request_configure.link); wl_list_remove(&v->request_activate.link); }
	wlr_scene_node_destroy(&v->tree->node);
	free(v);
}

static void new_xdg_toplevel(struct wl_listener *l, void *d) {
	struct server *s = wl_container_of(l, s, new_xdg_toplevel); struct wlr_xdg_toplevel *t = d;
	struct view *v = calloc(1, sizeof(*v)); v->server = s; v->type = VIEW_XDG; v->xdg = t;
	view_create_tree(v);
	v->content = wlr_scene_xdg_surface_create(v->tree, t->base);
	t->base->data = v->content;
	wlr_scene_node_set_enabled(&v->tree->node, false);
	v->map.notify = view_map; wl_signal_add(&t->base->surface->events.map, &v->map);
	v->unmap.notify = view_unmap; wl_signal_add(&t->base->surface->events.unmap, &v->unmap);
	v->commit.notify = view_commit; wl_signal_add(&t->base->surface->events.commit, &v->commit);
	v->destroy.notify = view_destroy; wl_signal_add(&t->events.destroy, &v->destroy);
	v->request_move.notify = view_request_move; wl_signal_add(&t->events.request_move, &v->request_move);
	v->request_resize.notify = view_request_resize; wl_signal_add(&t->events.request_resize, &v->request_resize);
}

struct popup { struct wlr_xdg_popup *p; struct wl_listener commit, destroy; };
static void popup_commit(struct wl_listener *l, void *d) { struct popup *p = wl_container_of(l, p, commit); (void)d; if (p->p->base->initial_commit) wlr_xdg_surface_schedule_configure(p->p->base); }
static void popup_destroy(struct wl_listener *l, void *d) { struct popup *p = wl_container_of(l, p, destroy); (void)d; wl_list_remove(&p->commit.link); wl_list_remove(&p->destroy.link); free(p); }
static void new_xdg_popup(struct wl_listener *l, void *d) {
	(void)l; struct wlr_xdg_popup *xp = d; struct popup *p = calloc(1, sizeof(*p)); p->p = xp;
	struct wlr_xdg_surface *parent = wlr_xdg_surface_try_from_wlr_surface(xp->parent);
	struct wlr_scene_tree *pt = NULL;
	if (parent) pt = parent->data;
	else { struct wlr_layer_surface_v1 *pl = wlr_layer_surface_v1_try_from_wlr_surface(xp->parent); if (pl) pt = pl->data; }
	if (pt) xp->base->data = wlr_scene_xdg_surface_create(pt, xp->base);
	p->commit.notify = popup_commit; wl_signal_add(&xp->base->surface->events.commit, &p->commit);
	p->destroy.notify = popup_destroy; wl_signal_add(&xp->events.destroy, &p->destroy);
}

/* ---------------- Xwayland ---------------- */
static void x11_associate(struct wl_listener *l, void *d) {
	struct view *v = wl_container_of(l, v, associate); (void)d;
	v->map.notify = view_map; wl_signal_add(&v->xs->surface->events.map, &v->map);
	v->unmap.notify = view_unmap; wl_signal_add(&v->xs->surface->events.unmap, &v->unmap);
	v->commit.notify = view_commit; wl_signal_add(&v->xs->surface->events.commit, &v->commit);
}
static void x11_dissociate(struct wl_listener *l, void *d) {
	struct view *v = wl_container_of(l, v, dissociate); (void)d;
	wl_list_remove(&v->map.link); wl_list_remove(&v->unmap.link); wl_list_remove(&v->commit.link);
}
static void x11_request_configure(struct wl_listener *l, void *d) {
	struct view *v = wl_container_of(l, v, request_configure); struct wlr_xwayland_surface_configure_event *e = d;
	wlr_xwayland_surface_configure(v->xs, e->x, e->y, e->width, e->height);
	wlr_scene_node_set_position(&v->tree->node, e->x, e->y);
}
static void x11_request_activate(struct wl_listener *l, void *d) { struct view *v = wl_container_of(l, v, request_activate); (void)d; if (v->mapped) focus_view(v); }
static void xwl_new_surface(struct wl_listener *l, void *d) {
	struct server *s = wl_container_of(l, s, xwl_new_surface); struct wlr_xwayland_surface *xs = d;
	struct view *v = calloc(1, sizeof(*v)); v->server = s; v->type = VIEW_X11; v->xs = xs;
	view_create_tree(v);
	v->associate.notify = x11_associate; wl_signal_add(&xs->events.associate, &v->associate);
	v->dissociate.notify = x11_dissociate; wl_signal_add(&xs->events.dissociate, &v->dissociate);
	v->destroy.notify = view_destroy; wl_signal_add(&xs->events.destroy, &v->destroy);
	v->request_configure.notify = x11_request_configure; wl_signal_add(&xs->events.request_configure, &v->request_configure);
	v->request_activate.notify = x11_request_activate; wl_signal_add(&xs->events.request_activate, &v->request_activate);
	v->request_move.notify = view_request_move; wl_signal_add(&xs->events.request_move, &v->request_move);
	v->request_resize.notify = view_request_resize; wl_signal_add(&xs->events.request_resize, &v->request_resize);
}
static void xwl_ready(struct wl_listener *l, void *d) {
	struct server *s = wl_container_of(l, s, xwl_ready); (void)d;
	wlr_xwayland_set_seat(s->xwayland, s->seat);
	wlr_log(WLR_INFO, "Xwayland ready on DISPLAY=%s", s->xwayland->display_name);
}

/* ---------------- layer shell ---------------- */
static void arrange_layers(struct server *s) {
	struct output *o;
	wl_list_for_each(o, &s->outputs, link) {
		struct wlr_box full; wlr_output_layout_get_box(s->output_layout, o->wlr, &full);
		struct wlr_box usable = full;
		for (int li = 3; li >= 0; li--) {   /* overlay/top first so their exclusive zones shrink the area for lower layers */
			struct layer *ly;
			wl_list_for_each(ly, &s->layer_surfaces, link)
				if (ly->ls->output == o->wlr && (int)ly->ls->current.layer == li && ly->ls->initialized)
					wlr_scene_layer_surface_v1_configure(ly->sls, &full, &usable);
		}
		wlr_scene_rect_set_size(s->bg, full.width, full.height);
		s->usable = usable;
	}
}
static void layer_commit(struct wl_listener *l, void *d) {
	struct layer *ly = wl_container_of(l, ly, commit); (void)d;
	if (ly->ls->initial_commit || ly->ls->current.committed) {
		wlr_scene_node_reparent(&ly->sls->tree->node, ly->server->layer[ly->ls->current.layer]);
		arrange_layers(ly->server);
	}
}
static void layer_map(struct wl_listener *l, void *d) {
	struct layer *ly = wl_container_of(l, ly, map); (void)d; arrange_layers(ly->server);
	if (ly->ls->current.keyboard_interactive) {
		struct wlr_keyboard *kb = wlr_seat_get_keyboard(ly->server->seat);
		if (kb) wlr_seat_keyboard_notify_enter(ly->server->seat, ly->ls->surface, kb->keycodes, kb->num_keycodes, &kb->modifiers);
		else wlr_seat_keyboard_notify_enter(ly->server->seat, ly->ls->surface, NULL, 0, NULL);
	}
}
static void layer_unmap(struct wl_listener *l, void *d) {
	struct layer *ly = wl_container_of(l, ly, unmap); (void)d; struct server *s = ly->server; arrange_layers(s);
	if (s->seat->keyboard_state.focused_surface == ly->ls->surface) {   /* give focus back to the top window */
		wlr_seat_keyboard_clear_focus(s->seat);
		if (!wl_list_empty(&s->views)) { struct view *v = wl_container_of(s->views.next, v, link); focus_view(v); }
	}
}
static void layer_destroy(struct wl_listener *l, void *d) {
	struct layer *ly = wl_container_of(l, ly, destroy); (void)d;
	wl_list_remove(&ly->link); wl_list_remove(&ly->commit.link); wl_list_remove(&ly->map.link); wl_list_remove(&ly->unmap.link); wl_list_remove(&ly->destroy.link);
	struct server *s = ly->server; free(ly); arrange_layers(s);
}
static void new_layer_surface(struct wl_listener *l, void *d) {
	struct server *s = wl_container_of(l, s, new_layer_surface); struct wlr_layer_surface_v1 *ls = d;
	if (!ls->output) {
		if (wl_list_empty(&s->outputs)) { wlr_layer_surface_v1_destroy(ls); return; }
		struct output *o = wl_container_of(s->outputs.next, o, link); ls->output = o->wlr;
	}
	struct layer *ly = calloc(1, sizeof(*ly)); ly->server = s; ly->ls = ls;
	ly->sls = wlr_scene_layer_surface_v1_create(s->layer[ls->pending.layer], ls);
	ls->data = ly->sls->tree;
	wl_list_insert(&s->layer_surfaces, &ly->link);
	ly->commit.notify = layer_commit; wl_signal_add(&ls->surface->events.commit, &ly->commit);
	ly->map.notify = layer_map; wl_signal_add(&ls->surface->events.map, &ly->map);
	ly->unmap.notify = layer_unmap; wl_signal_add(&ls->surface->events.unmap, &ly->unmap);
	ly->destroy.notify = layer_destroy; wl_signal_add(&ls->events.destroy, &ly->destroy);
}

/* ---------------- keyboard ---------------- */
static bool keybinding(struct server *s, xkb_keysym_t sym, uint32_t mods) {
	if ((mods & WLR_MODIFIER_LOGO) && (mods & WLR_MODIFIER_SHIFT) && sym == XKB_KEY_Escape) { wl_display_terminate(s->display); return true; }
	if (mods & WLR_MODIFIER_LOGO) {
		if (sym == XKB_KEY_Return) { spawn(s, s->terminal); return true; }
		if (sym == XKB_KEY_Left || sym == XKB_KEY_Right || sym == XKB_KEY_Up || sym == XKB_KEY_Down) {
			if (wl_list_empty(&s->views)) return true;
			struct view *v = wl_container_of(s->views.next, v, link);
			int m = sym == XKB_KEY_Left ? SNAP_LEFT : sym == XKB_KEY_Right ? SNAP_RIGHT : sym == XKB_KEY_Up ? SNAP_MAX : SNAP_NONE;
			if (m == v->snap && m != SNAP_NONE) m = SNAP_NONE;   /* pressing again restores */
			view_snap(v, m); return true;
		}
		if (sym == XKB_KEY_q || sym == XKB_KEY_Q) {
			if (wl_list_empty(&s->views)) return true;
			struct view *v = wl_container_of(s->views.next, v, link);
			if (v->type == VIEW_XDG) wlr_xdg_toplevel_send_close(v->xdg); else wlr_xwayland_surface_close(v->xs);
			return true;
		}
	}
	if ((mods & WLR_MODIFIER_ALT) && sym == XKB_KEY_Tab) {
		if (wl_list_length(&s->views) < 2) return true;
		struct view *n = wl_container_of(s->views.prev, n, link); focus_view(n); return true;
	}
	return false;
}
static void kb_modifiers(struct wl_listener *l, void *d) {
	struct keyboard *k = wl_container_of(l, k, modifiers); (void)d;
	wlr_seat_set_keyboard(k->server->seat, k->wlr); wlr_seat_keyboard_notify_modifiers(k->server->seat, &k->wlr->modifiers);
}
static void kb_key(struct wl_listener *l, void *d) {
	struct keyboard *k = wl_container_of(l, k, key); struct server *s = k->server; struct wlr_keyboard_key_event *e = d;
	const xkb_keysym_t *syms; int n = xkb_state_key_get_syms(k->wlr->xkb_state, e->keycode + 8, &syms);
	uint32_t mods = wlr_keyboard_get_modifiers(k->wlr); bool handled = false;
	for (int i = 0; i < n; i++) {
		bool super = syms[i] == XKB_KEY_Super_L || syms[i] == XKB_KEY_Super_R;
		if (super) {   /* ChromeOS-style: tapping Super alone opens the launcher */
			if (e->state == WL_KEYBOARD_KEY_STATE_PRESSED) s->super_alone = true;
			else if (s->super_alone) { s->super_alone = false; spawn(s, s->launcher); }
		} else if (e->state == WL_KEYBOARD_KEY_STATE_PRESSED) {
			s->super_alone = false;
			handled |= keybinding(s, syms[i], mods);
		}
	}
	if (!handled) { wlr_seat_set_keyboard(s->seat, k->wlr); wlr_seat_keyboard_notify_key(s->seat, e->time_msec, e->keycode, e->state); }
}
static void kb_destroy(struct wl_listener *l, void *d) {
	struct keyboard *k = wl_container_of(l, k, destroy); (void)d;
	wl_list_remove(&k->modifiers.link); wl_list_remove(&k->key.link); wl_list_remove(&k->destroy.link); wl_list_remove(&k->link); free(k);
}
static void add_keyboard(struct server *s, struct wlr_keyboard *wk) {
	struct keyboard *k = calloc(1, sizeof(*k)); k->server = s; k->wlr = wk;
	struct xkb_context *ctx = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
	struct xkb_rule_names names = { .layout = getenv("XKB_DEFAULT_LAYOUT") ? getenv("XKB_DEFAULT_LAYOUT") : "us" };
	struct xkb_keymap *km = xkb_keymap_new_from_names(ctx, &names, XKB_KEYMAP_COMPILE_NO_FLAGS);
	if (wk->keymap == NULL) wlr_keyboard_set_keymap(wk, km);   /* virtual keyboards bring their own keymap */
	xkb_keymap_unref(km); xkb_context_unref(ctx);
	wlr_keyboard_set_repeat_info(wk, 25, 600);
	k->modifiers.notify = kb_modifiers; wl_signal_add(&wk->events.modifiers, &k->modifiers);
	k->key.notify = kb_key; wl_signal_add(&wk->events.key, &k->key);
	k->destroy.notify = kb_destroy; wl_signal_add(&wk->base.events.destroy, &k->destroy);
	wlr_seat_set_keyboard(s->seat, wk);
	wl_list_insert(&s->keyboards, &k->link);
	wlr_seat_set_capabilities(s->seat, WL_SEAT_CAPABILITY_POINTER | WL_SEAT_CAPABILITY_KEYBOARD);
}
static void new_input(struct wl_listener *l, void *d) {
	struct server *s = wl_container_of(l, s, new_input); struct wlr_input_device *dev = d;
	if (dev->type == WLR_INPUT_DEVICE_KEYBOARD) add_keyboard(s, wlr_keyboard_from_input_device(dev));
	else if (dev->type == WLR_INPUT_DEVICE_POINTER) wlr_cursor_attach_input_device(s->cursor, dev);
	wlr_seat_set_capabilities(s->seat, WL_SEAT_CAPABILITY_POINTER | (wl_list_empty(&s->keyboards) ? 0 : WL_SEAT_CAPABILITY_KEYBOARD));
}
static void new_vkbd(struct wl_listener *l, void *d) {
	struct server *s = wl_container_of(l, s, new_vkbd); struct wlr_virtual_keyboard_v1 *vk = d; add_keyboard(s, &vk->keyboard);
}
static void new_vptr(struct wl_listener *l, void *d) {
	struct server *s = wl_container_of(l, s, new_vptr); struct wlr_virtual_pointer_v1_new_pointer_event *e = d;
	wlr_cursor_attach_input_device(s->cursor, &e->new_pointer->pointer.base);
}
static void new_deco(struct wl_listener *l, void *d) { (void)l; struct wlr_xdg_toplevel_decoration_v1 *dec = d; wlr_xdg_toplevel_decoration_v1_set_mode(dec, WLR_XDG_TOPLEVEL_DECORATION_V1_MODE_CLIENT_SIDE); }

static void request_cursor(struct wl_listener *l, void *d) {
	struct server *s = wl_container_of(l, s, request_cursor); struct wlr_seat_pointer_request_set_cursor_event *e = d;
	if (s->seat->pointer_state.focused_client == e->seat_client) wlr_cursor_set_surface(s->cursor, e->surface, e->hotspot_x, e->hotspot_y);
}
static void request_set_selection(struct wl_listener *l, void *d) {
	struct server *s = wl_container_of(l, s, request_set_selection); struct wlr_seat_request_set_selection_event *e = d;
	wlr_seat_set_selection(s->seat, e->source, e->serial);
}

/* ---------------- pointer ---------------- */
static void process_motion(struct server *s, uint32_t time) {
	if (s->mode == CUR_MOVE) { wlr_scene_node_set_position(&s->grabbed->tree->node, s->cursor->x - s->grab_x, s->cursor->y - s->grab_y);
		s->grabbed->has_target = false;
		if (s->grabbed->type == VIEW_X11) wlr_xwayland_surface_configure(s->grabbed->xs, s->grabbed->tree->node.x, s->grabbed->tree->node.y, s->grabbed->xs->width, s->grabbed->xs->height);
		return; }
	if (s->mode == CUR_RESIZE) {
		double bx = s->cursor->x - s->grab_x, by = s->cursor->y - s->grab_y;
		int l = s->grab_box.x, r = s->grab_box.x + s->grab_box.width, t = s->grab_box.y, b = s->grab_box.y + s->grab_box.height;
		if (s->resize_edges & WLR_EDGE_TOP) { t = by; if (t >= b) t = b - 1; } else if (s->resize_edges & WLR_EDGE_BOTTOM) { b = by; if (b <= t) b = t + 1; }
		if (s->resize_edges & WLR_EDGE_LEFT) { l = bx; if (l >= r) l = r - 1; } else if (s->resize_edges & WLR_EDGE_RIGHT) { r = bx; if (r <= l) r = l + 1; }
		view_set_size(s->grabbed, l, t, r - l, b - t); return;
	}
	double sx, sy; struct wlr_surface *surf = NULL;
	struct view *v = view_at(s, s->cursor->x, s->cursor->y, &surf, &sx, &sy);
	if (!v && !surf) wlr_cursor_set_xcursor(s->cursor, s->xcursor, "default");
	if (surf) { wlr_seat_pointer_notify_enter(s->seat, surf, sx, sy); wlr_seat_pointer_notify_motion(s->seat, time, sx, sy); }
	else wlr_seat_pointer_clear_focus(s->seat);
}
static void cursor_motion(struct wl_listener *l, void *d) {
	struct server *s = wl_container_of(l, s, cursor_motion); struct wlr_pointer_motion_event *e = d;
	wlr_cursor_move(s->cursor, &e->pointer->base, e->delta_x, e->delta_y); process_motion(s, e->time_msec);
}
static void cursor_motion_abs(struct wl_listener *l, void *d) {
	struct server *s = wl_container_of(l, s, cursor_motion_abs); struct wlr_pointer_motion_absolute_event *e = d;
	wlr_cursor_warp_absolute(s->cursor, &e->pointer->base, e->x, e->y); process_motion(s, e->time_msec);
}
static void cursor_button(struct wl_listener *l, void *d) {
	struct server *s = wl_container_of(l, s, cursor_button); struct wlr_pointer_button_event *e = d;
	if (e->state == WL_POINTER_BUTTON_STATE_RELEASED) {
		if (s->mode != CUR_PASS) {
			if (s->mode == CUR_MOVE && s->grabbed) {   /* drag to an edge: snap */
				struct wlr_box u = usable_area(s); int m = SNAP_NONE;
				if (s->cursor->x <= u.x + 4) m = SNAP_LEFT; else if (s->cursor->x >= u.x + u.width - 5) m = SNAP_RIGHT;
				else if (s->cursor->y <= u.y + 4) m = SNAP_MAX;
				if (m != SNAP_NONE) view_snap(s->grabbed, m);
			}
			s->mode = CUR_PASS; s->grabbed = NULL; return; }
		wlr_seat_pointer_notify_button(s->seat, e->time_msec, e->button, e->state); return;
	}
	double sx, sy; struct wlr_surface *surf = NULL;
	struct view *v = view_at(s, s->cursor->x, s->cursor->y, &surf, &sx, &sy);
	struct wlr_keyboard *kb = wlr_seat_get_keyboard(s->seat);
	if (v && kb && (wlr_keyboard_get_modifiers(kb) & WLR_MODIFIER_LOGO)) {   /* Super+drag: move (left) / resize (right) */
		s->super_alone = false; focus_view(v);
		if (e->button == 0x110) begin_grab(v, CUR_MOVE, 0); else begin_grab(v, CUR_RESIZE, WLR_EDGE_RIGHT | WLR_EDGE_BOTTOM);
		return;
	}
	if (v) focus_view(v);
	wlr_seat_pointer_notify_button(s->seat, e->time_msec, e->button, e->state);
}
static void cursor_axis(struct wl_listener *l, void *d) {
	struct server *s = wl_container_of(l, s, cursor_axis); struct wlr_pointer_axis_event *e = d;
	wlr_seat_pointer_notify_axis(s->seat, e->time_msec, e->orientation, e->delta, e->delta_discrete, e->source, e->relative_direction);
}
static void cursor_frame(struct wl_listener *l, void *d) { struct server *s = wl_container_of(l, s, cursor_frame); (void)d; wlr_seat_pointer_notify_frame(s->seat); }

/* ---------------- outputs ---------------- */
static void output_frame(struct wl_listener *l, void *d) {
	struct output *o = wl_container_of(l, o, frame); (void)d;
	struct wlr_scene_output *so = wlr_scene_get_scene_output(o->server->scene, o->wlr);
	wlr_scene_output_commit(so, NULL);
	struct timespec now; clock_gettime(CLOCK_MONOTONIC, &now); wlr_scene_output_send_frame_done(so, &now);
}
static void output_request_state(struct wl_listener *l, void *d) { struct output *o = wl_container_of(l, o, request_state); const struct wlr_output_event_request_state *e = d; wlr_output_commit_state(o->wlr, e->state); }
static void output_destroy(struct wl_listener *l, void *d) {
	struct output *o = wl_container_of(l, o, destroy); (void)d;
	wl_list_remove(&o->frame.link); wl_list_remove(&o->request_state.link); wl_list_remove(&o->destroy.link); wl_list_remove(&o->link); free(o);
}
static void new_output(struct wl_listener *l, void *d) {
	struct server *s = wl_container_of(l, s, new_output); struct wlr_output *wo = d;
	wlr_output_init_render(wo, s->allocator, s->renderer);
	struct wlr_output_state st; wlr_output_state_init(&st); wlr_output_state_set_enabled(&st, true);
	struct wlr_output_mode *m = wlr_output_preferred_mode(wo); if (m) wlr_output_state_set_mode(&st, m);
	wlr_output_commit_state(wo, &st); wlr_output_state_finish(&st);
	struct output *o = calloc(1, sizeof(*o)); o->server = s; o->wlr = wo;
	o->frame.notify = output_frame; wl_signal_add(&wo->events.frame, &o->frame);
	o->request_state.notify = output_request_state; wl_signal_add(&wo->events.request_state, &o->request_state);
	o->destroy.notify = output_destroy; wl_signal_add(&wo->events.destroy, &o->destroy);
	wl_list_insert(&s->outputs, &o->link);
	struct wlr_output_layout_output *lo = wlr_output_layout_add_auto(s->output_layout, wo);
	struct wlr_scene_output *so = wlr_scene_output_create(s->scene, wo);
	wlr_scene_output_layout_add_output(s->scene_layout, lo, so);
	arrange_layers(s);
}

static void add_headless_output(struct wlr_backend *b, void *data) {
	if (wlr_backend_is_headless(b)) { int *wh = data; wlr_headless_add_output(b, wh[0], wh[1]); }
}

int main(int argc, char *argv[]) {
	wlr_log_init(getenv("POLDER_COMP_DEBUG") ? WLR_DEBUG : WLR_INFO, NULL);
	char *startup = NULL; int c;
	while ((c = getopt(argc, argv, "s:h")) != -1) { if (c == 's') startup = optarg; else { printf("Usage: %s [-s startup-command]\n", argv[0]); return 0; } }
	struct server s = {0};
	s.launcher = getenv("POLDER_LAUNCHER") ? getenv("POLDER_LAUNCHER") : "polder-launcher";
	s.terminal = getenv("POLDER_TERMINAL") ? getenv("POLDER_TERMINAL") : "foot";
	read_palette(&s);
	s.display = wl_display_create();
	setenv("WLR_HEADLESS_OUTPUTS", "0", 0); /* we add our own 1366x768 output */
	setenv("GTK_IM_MODULE", "gtk-im-context-simple", 0);   /* no text-input-v3 yet: GTK3 wayland IM would swallow typed text */
	s.backend = wlr_backend_autocreate(wl_display_get_event_loop(s.display), NULL);
	if (!s.backend) { wlr_log(WLR_ERROR, "no backend"); return 1; }
#ifdef POLDER_SCENEFX
	s.renderer = fx_renderer_create(s.backend);
#else
	s.renderer = wlr_renderer_autocreate(s.backend);
#endif
	if (!s.renderer) { wlr_log(WLR_ERROR, "no renderer (scenefx needs GLES2)"); return 1; }
	wlr_renderer_init_wl_display(s.renderer, s.display);
	s.allocator = wlr_allocator_autocreate(s.backend, s.renderer);
	s.compositor = wlr_compositor_create(s.display, 5, s.renderer);
	wlr_subcompositor_create(s.display);
	wlr_data_device_manager_create(s.display);
	wlr_data_control_manager_v1_create(s.display);
	wlr_primary_selection_v1_device_manager_create(s.display);
	wlr_viewporter_create(s.display);
	s.output_layout = wlr_output_layout_create(s.display);
	wl_list_init(&s.outputs); wl_list_init(&s.views); wl_list_init(&s.layer_surfaces); wl_list_init(&s.keyboards);
	s.new_output.notify = new_output; wl_signal_add(&s.backend->events.new_output, &s.new_output);
	s.scene = wlr_scene_create();
	s.scene_layout = wlr_scene_attach_output_layout(s.scene, s.output_layout);
	s.bg = wlr_scene_rect_create(&s.scene->tree, 1366, 768, s.bg_color);
	s.layer[0] = wlr_scene_tree_create(&s.scene->tree); s.layer[1] = wlr_scene_tree_create(&s.scene->tree);
	s.views_tree = wlr_scene_tree_create(&s.scene->tree);
	s.layer[2] = wlr_scene_tree_create(&s.scene->tree); s.unmanaged_tree = wlr_scene_tree_create(&s.scene->tree);
	s.layer[3] = wlr_scene_tree_create(&s.scene->tree);
	s.xdg_shell = wlr_xdg_shell_create(s.display, 3);
	s.new_xdg_toplevel.notify = new_xdg_toplevel; wl_signal_add(&s.xdg_shell->events.new_toplevel, &s.new_xdg_toplevel);
	s.new_xdg_popup.notify = new_xdg_popup; wl_signal_add(&s.xdg_shell->events.new_popup, &s.new_xdg_popup);
	s.layer_shell = wlr_layer_shell_v1_create(s.display, 4);
	s.new_layer_surface.notify = new_layer_surface; wl_signal_add(&s.layer_shell->events.new_surface, &s.new_layer_surface);
	struct wlr_xdg_decoration_manager_v1 *deco = wlr_xdg_decoration_manager_v1_create(s.display);
	s.new_deco.notify = new_deco; wl_signal_add(&deco->events.new_toplevel_decoration, &s.new_deco);
	wlr_screencopy_manager_v1_create(s.display);
	wlr_xdg_output_manager_v1_create(s.display, s.output_layout);
	s.cursor = wlr_cursor_create(); wlr_cursor_attach_output_layout(s.cursor, s.output_layout);
	s.xcursor = wlr_xcursor_manager_create(NULL, 24);
	s.cursor_motion.notify = cursor_motion; wl_signal_add(&s.cursor->events.motion, &s.cursor_motion);
	s.cursor_motion_abs.notify = cursor_motion_abs; wl_signal_add(&s.cursor->events.motion_absolute, &s.cursor_motion_abs);
	s.cursor_button.notify = cursor_button; wl_signal_add(&s.cursor->events.button, &s.cursor_button);
	s.cursor_axis.notify = cursor_axis; wl_signal_add(&s.cursor->events.axis, &s.cursor_axis);
	s.cursor_frame.notify = cursor_frame; wl_signal_add(&s.cursor->events.frame, &s.cursor_frame);
	s.new_input.notify = new_input; wl_signal_add(&s.backend->events.new_input, &s.new_input);
	s.seat = wlr_seat_create(s.display, "seat0");
	s.request_cursor.notify = request_cursor; wl_signal_add(&s.seat->events.request_set_cursor, &s.request_cursor);
	s.request_set_selection.notify = request_set_selection; wl_signal_add(&s.seat->events.request_set_selection, &s.request_set_selection);
	struct wlr_virtual_keyboard_manager_v1 *vk = wlr_virtual_keyboard_manager_v1_create(s.display);
	s.new_vkbd.notify = new_vkbd; wl_signal_add(&vk->events.new_virtual_keyboard, &s.new_vkbd);
	struct wlr_virtual_pointer_manager_v1 *vp = wlr_virtual_pointer_manager_v1_create(s.display);
	s.new_vptr.notify = new_vptr; wl_signal_add(&vp->events.new_virtual_pointer, &s.new_vptr);
	wlr_seat_set_capabilities(s.seat, WL_SEAT_CAPABILITY_POINTER);

	const char *sock = wl_display_add_socket_auto(s.display);
	if (!sock || !wlr_backend_start(s.backend)) { wlr_log(WLR_ERROR, "start failed"); return 1; }
	int wh[2] = { 1366, 768 }; wlr_multi_for_each_backend(s.backend, add_headless_output, wh);
	setenv("WAYLAND_DISPLAY", sock, true);
	if (!getenv("POLDER_NO_XWAYLAND")) {
		s.xwayland = wlr_xwayland_create(s.display, s.compositor, false);
		if (s.xwayland) {
			s.xwl_ready.notify = xwl_ready; wl_signal_add(&s.xwayland->events.ready, &s.xwl_ready);
			s.xwl_new_surface.notify = xwl_new_surface; wl_signal_add(&s.xwayland->events.new_surface, &s.xwl_new_surface);
			setenv("DISPLAY", s.xwayland->display_name, true);
		}
	}
	wlr_log(WLR_INFO, "polder-comp on WAYLAND_DISPLAY=%s DISPLAY=%s", sock, getenv("DISPLAY") ? getenv("DISPLAY") : "-");
	if (startup) spawn(&s, startup);
	wl_display_run(s.display);
	if (s.xwayland) wlr_xwayland_destroy(s.xwayland);
	wl_display_destroy_clients(s.display);
	wlr_scene_node_destroy(&s.scene->tree.node);
	wlr_xcursor_manager_destroy(s.xcursor); wlr_cursor_destroy(s.cursor);
	wlr_allocator_destroy(s.allocator); wlr_renderer_destroy(s.renderer); wlr_backend_destroy(s.backend);
	wl_display_destroy(s.display);
	return 0;
}
