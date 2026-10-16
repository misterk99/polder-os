/* pc-drag X1 Y1 X2 Y2 [W H]: real press-move-release drag via wlr-virtual-pointer (test helper); was: pc-click X Y [button 272=left 273=right 274=middle] [W H]: real click via wlr-virtual-pointer (test helper) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <wayland-client.h>
#include "vp.h"
static struct zwlr_virtual_pointer_manager_v1 *mgr; static struct wl_seat *seat;
static void reg(void *d, struct wl_registry *r, uint32_t n, const char *i, uint32_t v) {
	if (!strcmp(i, zwlr_virtual_pointer_manager_v1_interface.name)) mgr = wl_registry_bind(r, n, &zwlr_virtual_pointer_manager_v1_interface, 1);
	else if (!strcmp(i, wl_seat_interface.name)) seat = wl_registry_bind(r, n, &wl_seat_interface, 1);
}
static void unreg(void *d, struct wl_registry *r, uint32_t n) {}
static const struct wl_registry_listener rl = { reg, unreg };
int main(int c, char **v) {
	int x1 = atoi(v[1]), y1 = atoi(v[2]), x2 = atoi(v[3]), y2 = atoi(v[4]), W = c > 6 ? atoi(v[5]) : 1366, H = c > 6 ? atoi(v[6]) : 768, t = 2;
	struct wl_display *d = wl_display_connect(NULL); if (!d) return 1;
	wl_registry_add_listener(wl_display_get_registry(d), &rl, NULL); wl_display_roundtrip(d); if (!mgr) return 2;
	struct zwlr_virtual_pointer_v1 *p = zwlr_virtual_pointer_manager_v1_create_virtual_pointer(mgr, seat);
	zwlr_virtual_pointer_v1_motion_absolute(p, 1, x1, y1, W, H); zwlr_virtual_pointer_v1_frame(p); wl_display_roundtrip(d); usleep(100000);
	zwlr_virtual_pointer_v1_button(p, t++, 272, 1); zwlr_virtual_pointer_v1_frame(p); wl_display_roundtrip(d); usleep(100000);
	for (int i = 1; i <= 30; i++) { zwlr_virtual_pointer_v1_motion_absolute(p, t++, x1 + (x2 - x1) * i / 30, y1 + (y2 - y1) * i / 30, W, H); zwlr_virtual_pointer_v1_frame(p); wl_display_roundtrip(d); usleep(25000); }
	usleep(200000);
	zwlr_virtual_pointer_v1_button(p, t++, 272, 0); zwlr_virtual_pointer_v1_frame(p); wl_display_roundtrip(d); usleep(100000);
	return 0;
}
