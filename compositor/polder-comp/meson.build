project('polder-comp', 'c', version: '0.1', default_options: ['c_std=c11', 'warning_level=2'])
add_project_arguments('-DWLR_USE_UNSTABLE', '-Wno-unused-parameter', language: 'c')
wayland_protos = dependency('wayland-protocols')
wl_scanner = find_program('wayland-scanner')
wp_dir = wayland_protos.get_variable('pkgdatadir')
protos = []
foreach p : [['stable/xdg-shell/xdg-shell.xml', 'xdg-shell-protocol.h'], ['unstable/xdg-decoration/xdg-decoration-unstable-v1.xml', 'xdg-decoration-unstable-v1-protocol.h']]
  protos += custom_target(p[1], input: wp_dir / p[0], output: p[1], command: [wl_scanner, 'server-header', '@INPUT@', '@OUTPUT@'])
endforeach
protos += custom_target('wlr-layer-shell-unstable-v1-protocol.h', input: 'protocols/wlr-layer-shell-unstable-v1.xml', output: 'wlr-layer-shell-unstable-v1-protocol.h', command: [wl_scanner, 'server-header', '@INPUT@', '@OUTPUT@'])
deps = [dependency('wlroots-0.18'), dependency('wayland-server'), dependency('xkbcommon'), dependency('xcb')]
scenefx = dependency('scenefx-0.2', required: get_option('scenefx'))
args = []
if scenefx.found()
  # scenefx must come BEFORE wlroots: both export wlr_scene_*; libwlroots' copy would otherwise win at runtime
  # and mix two scene-graph implementations (invisible rounded buffers, crashes) -- found in the qemu test
  deps = [scenefx] + deps
  args += '-DPOLDER_SCENEFX'
endif
executable('polder-comp', 'polder-comp.c', protos, dependencies: deps, c_args: args, link_args: ['-rdynamic'], install: true)
