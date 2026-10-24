from process import *
from pygw import *
import signal
import itertools

class Hooks:
    def __init__(self):
        self.finv_caches = {}

    @Hook.stdcall(LPVOID, LPVOID, LPVOID, FLOAT, DWORD, LPVOID, LPVOID)
    def path_find_impl(self, path_context, src_pos, dst_pos, max_cost, max_count, path_count, path_array):
        sx, sy, sp = proc.read(src_pos, 'ffI')
        dx, dy, dp = proc.read(dst_pos, 'ffI')
        print(f'PathFindImpl ({sx}, {sy}, {sp}) -> ({dx}, {dy}, {dp}), max_cost: {max_cost:.4f}')

    @Hook.rawcall
    def path_find_caller_impl(self, ctx):
        max_count, path_count_ptr, path_array_ptr = proc.read(ctx.Ebp + 0x18, 'III')
        path_count, = proc.read(path_count_ptr, 'I')
        segments = proc.read(path_array_ptr, 'ffII' * path_count)
        for idx, (x, y, plane, _) in enumerate(itertools.batched(segments, 4)):
            print(f'res: {idx}, {x:.4f}, {y:.4f}, {plane}')

    @Hook.stdcall(LPVOID, LPVOID, LPVOID, FLOAT, FLOAT)
    def astart_add_node(self, path_ctx, parent_path_map, neighbor_seg, current_cost, estimated_cost):
        x, y, p, trap = proc.read(neighbor_seg, 'ffII')
        trap_id, = proc.read(trap, 'I')
        print(f'astart_add_node: ({x:.4f}, {y:.4f}, {p}), trap: {trap_id}, cost: {current_cost:.4f}, estimated_cost: {estimated_cost:.4f}')
        pass

    @Hook.stdcall(LPVOID, LPVOID, LPVOID, LPVOID, FLOAT, LPVOID)
    def visit_trap_above(self, path_ctx, current_path_map, current_pos, dst_pos, max_cost, visited_trap):
        print('visit_trap_above')
        pass

    @Hook.stdcall(LPVOID, LPVOID, LPVOID, LPVOID, FLOAT, LPVOID)
    def visit_trap_bellow(self, path_ctx, current_path_map, current_pos, dst_pos, max_cost, visited_trap):
        print('visit_trap_bellow')
        pass

    @Hook.stdcall(LPVOID, LPVOID, LPVOID, LPVOID, FLOAT, DWORD)
    def visit_portal_left(self, path_ctx, current_path_map, current_pos, dst_pos, max_cost, portal_id):
        print(f'visit_portal_left portal id: {portal_id}')
        pass

    @Hook.stdcall(LPVOID, LPVOID, LPVOID, LPVOID, FLOAT, DWORD)
    def visit_portal_right(self, path_ctx, current_path_map, current_pos, dst_pos, max_cost, portal_id):
        print(f'visit_portal_right portal id: {portal_id}')
        pass

    @Hook.stdcall(LPVOID, LPVOID, LPVOID, LPVOID, LPVOID, LPVOID, FLOAT)
    def visit_trapezoid(self, path_ctx, current_path_map, current_pos, dst_pos, visited_seg, visited_trap, max_cost):
        x, y, p = proc.read(visited_seg, 'ffI')
        print(f'visit_trapezoid: ({x:.4f}, {y:.4f}, {p})')

    @Hook.stdcall(LPVOID, LPVOID, LPVOID, LPVOID, LPVOID, LPVOID)
    def pick_next_point(self, point1, point2, cur_pos, dst_pos, portal_trap, out_result):
        print('pick_next_point')
        pass

    @Hook.stdcall(FLOAT, FLOAT, FLOAT, LPVOID, LPVOID, LPVOID, LPVOID)
    def find_point_on_next_trap(self, left_x, right_x, next_y, current_pos, dst_pos, visited_trap, out_path_seg):
        cx, cy = proc.read(current_pos, 'ff')
        dx, dy = proc.read(dst_pos, 'ff')
        print(f'find_point_on_next_trap: lx: {left_x:.4f}, rx: {right_x:.4f}, next_y: {next_y:.4f}, current pos: ({cx:.4f}, {cy:.4f}), dst pos: ({dx:.4f}, {dy:.4f})')

    def prioq_push(self):
        pass

    @Hook.rawcall
    def finv(self, ctx, thread):
        value, = proc.read(ctx.Ecx, 'f')
        self.finv_caches[thread.id] = (ctx.Ecx, value)

    @Hook.rawcall
    def finv_ret(self, ctx, thread):
        ecx, input = self.finv_caches.pop(thread.id)
        result, = proc.read(ecx, 'f')
        print(f'{input},{result}')

    @Hook.thiscall(LPVOID, LPVOID, LPVOID, LPVOID, DWORD, LPVOID, LPVOID)
    def path_create_waypoint(self, helper, context, src_segment, dst_segment, max_count, path_count, path_buffer):
        src_trap, = proc.read(src_segment + 0xC)
        src_trap_id, = proc.read(src_trap)

        path_nodes = Array(*proc.read(context + 0x10, 'IIII'))
        src_node, = proc.read(path_nodes.buf + (src_trap_id * 4))
        curr_node = src_node

        while True:
            x, y, plane, trap, curr_node = proc.read(curr_node + 0x18, 'ffIII')
            print(f'Node {x:.4f}, {y:.4f}, {plane}')
            if curr_node == 0:
                break

    @Hook.thiscall(LPVOID, LPVOID, LPVOID, LPVOID, LPVOID)
    def path_build_process_next(self, helper, left, right, next_trap, path_node):
        lx, ly = proc.read(left, 'ff')
        rx, ry = proc.read(right, 'ff')
        next_trap_id, = proc.read(next_trap)
        current_trap_id, = proc.read(proc.read(proc.read(path_node)[0] + 0x24)[0])
        print(f'path_build_process_next: left: {lx:.4f}, {ly:.4f}, right: {rx:.4f}, {ry:.4f}, current_trap_id: {current_trap_id}, next_trap_id: {next_trap_id}')

    @Hook.thiscall(LPVOID, LPVOID, LPVOID, LPVOID)
    def path_build_add_waypoint(self, helper, left, right, path_node):
        lx, ly = proc.read(left, 'ff')
        rx, ry = proc.read(right, 'ff')
        current_trap_id, = proc.read(proc.read(proc.read(path_node)[0] + 0x24)[0])
        print(f'path_build_add_waypoint: left: {lx:.4f}, {ly:.4f}, right: {rx:.4f}, {ry:.4f}, current_trap_id: {current_trap_id}')

    @Hook.thiscall(LPVOID, LPVOID, LPVOID)
    def path_add_last(self, helper, path_node, dst_segment):
        current_trap_id, = proc.read(proc.read(proc.read(path_node)[0] + 0x24)[0])
        x, y, plane = proc.read(dst_segment, 'ffI')
        print(f'path_add_last: current_trap_id: {current_trap_id}, dst: {x:.4f}, {y:.4f}, {plane}')

    @Hook.thiscall(LPVOID, LPVOID, LPVOID)
    def path_build_add_waypoint_and_reduce(self, helper, new_point, from_pos):
        nx, ny, np, trap = proc.read(new_point, 'ffII')
        trap_id, = proc.read(trap)
        fx, fy = proc.read(from_pos, 'ff')
        print(f'path_build_add_waypoint_and_reduce: new: {nx:.4f}, {ny:.4f}, {np}, trap: {trap_id}, from: {fx:.4f}, {fy:.4f}')


if __name__ == '__main__':
    stop = False
    def signal_handler(sig, frame):
        global stop
        stop = True

    proc, = GetProcesses('Gw.exe')
    scanner = ProcessScanner(proc)
    base_addr = proc.module().base
    gw = pygw(proc)

    path_find_impl_rva = 0x3014E0
    path_find_impl_caller_rva = 0x2F8198
    astart_add_node_rva = 0x2FFC90
    visit_trap_above_rva = 0x3009E0
    visit_trap_bellow_rva = 0x300A90
    visit_portal_left_rva = 0x300B40
    visit_portal_right_rva = 0x300CE0
    visit_trapezoid_rva = 0x300E80
    find_point_on_next_trap_rva = 0x300890
    pick_next_point_rva = 0
    prioq_push_rva = 0

    path_create_waypoint_rva = 0x2FF650
    path_add_last_rva = 0x302220
    path_build_process_next_rva = 0x302430
    path_build_add_waypoint_rva = 0x302070
    path_build_add_waypoint_and_reduce_rva = 0x301DD0

    hooks = Hooks()

    prev_handler = signal.signal(signal.SIGINT, signal_handler)
    with ProcessDebugger(proc) as dbg:
        dbg.add_hook(base_addr + path_find_impl_rva, hooks.path_find_impl)
        dbg.add_hook(base_addr + path_find_impl_caller_rva, hooks.path_find_caller_impl)
        dbg.add_hook(base_addr + astart_add_node_rva, hooks.astart_add_node)
        dbg.add_hook(base_addr + visit_trap_above_rva, hooks.visit_trap_above)
        dbg.add_hook(base_addr + visit_trap_bellow_rva, hooks.visit_trap_bellow)
        dbg.add_hook(base_addr + visit_portal_left_rva, hooks.visit_portal_left)
        dbg.add_hook(base_addr + visit_portal_right_rva, hooks.visit_portal_right)
        dbg.add_hook(base_addr + visit_trapezoid_rva, hooks.visit_trapezoid)
        dbg.add_hook(base_addr + find_point_on_next_trap_rva, hooks.find_point_on_next_trap)

        dbg.add_hook(base_addr + path_create_waypoint_rva, hooks.path_create_waypoint)
        dbg.add_hook(base_addr + path_add_last_rva, hooks.path_add_last)
        dbg.add_hook(base_addr + path_build_process_next_rva, hooks.path_build_process_next)
        dbg.add_hook(base_addr + path_build_add_waypoint_rva, hooks.path_build_add_waypoint)
        dbg.add_hook(base_addr + path_build_add_waypoint_and_reduce_rva, hooks.path_build_add_waypoint_and_reduce)

        while not stop:
            dbg.poll(32)
