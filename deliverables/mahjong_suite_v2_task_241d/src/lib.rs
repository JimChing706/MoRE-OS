//! Tetris 核心逻辑库：SRS 踢墙、7-Bag、Hold、Ghost、Lock Delay。
//!
//! 所有算法均采用纯函数风格，便于单测与 WASM 编译。

#![allow(dead_code)]

/// 方块类型枚举（7 种标准 Tetromino）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum PieceType {
    I, O, T, S, Z, J, L,
}

/// 4 种旋转状态：0 / R / 2 / L。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum RotState {
    N0 = 0,
    R  = 1,
    N2 = 2,
    L  = 3,
}

impl RotState {
    pub fn cw(self) -> Self {
        match self {
            RotState::N0 => RotState::R,
            RotState::R  => RotState::N2,
            RotState::N2 => RotState::L,
            RotState::L  => RotState::N0,
        }
    }
    pub fn ccw(self) -> Self {
        match self {
            RotState::N0 => RotState::L,
            RotState::L  => RotState::N2,
            RotState::N2 => RotState::R,
            RotState::R  => RotState::N0,
        }
    }
}

/// 踢墙偏移量：(dx, dy)。
pub type KickOffset = (i32, i32);

/// SRS 标准踢墙表：键为 (方块类型 JLSTZ/I/O, 起始旋转, 目标旋转)。
/// O 型方块旋转无视觉变化，返回空表（直接成功）。
pub const SRS_KICKS: &[((PieceType, RotState, RotState), &[KickOffset])] = &[
    // ===== JLSTZ 共用 =====
    // 0 -> R
    ((PieceType::J, RotState::N0, RotState::R), &[(0,0),(-1,0),(-1,1),(0,-2),(-1,-2)]),
    ((PieceType::L, RotState::N0, RotState::R), &[(0,0),(-1,0),(-1,1),(0,-2),(-1,-2)]),
    ((PieceType::S, RotState::N0, RotState::R), &[(0,0),(-1,0),(-1,1),(0,-2),(-1,-2)]),
    ((PieceType::T, RotState::N0, RotState::R), &[(0,0),(-1,0),(-1,1),(0,-2),(-1,-2)]),
    ((PieceType::Z, RotState::N0, RotState::R), &[(0,0),(-1,0),(-1,1),(0,-2),(-1,-2)]),
    // R -> 0
    ((PieceType::J, RotState::R, RotState::N0), &[(0,0),(1,0),(1,-1),(0,2),(1,2)]),
    ((PieceType::L, RotState::R, RotState::N0), &[(0,0),(1,0),(1,-1),(0,2),(1,2)]),
    ((PieceType::S, RotState::R, RotState::N0), &[(0,0),(1,0),(1,-1),(0,2),(1,2)]),
    ((PieceType::T, RotState::R, RotState::N0), &[(0,0),(1,0),(1,-1),(0,2),(1,2)]),
    ((PieceType::Z, RotState::R, RotState::N0), &[(0,0),(1,0),(1,-1),(0,2),(1,2)]),
    // R -> 2
    ((PieceType::J, RotState::R, RotState::N2), &[(0,0),(1,0),(1,-1),(0,2),(1,2)]),
    ((PieceType::L, RotState::R, RotState::N2), &[(0,0),(1,0),(1,-1),(0,2),(1,2)]),
    ((PieceType::T, RotState::R, RotState::N2), &[(0,0),(1,0),(1,-1),(0,2),(1,2)]),
    // 2 -> R
    ((PieceType::J, RotState::N2, RotState::R), &[(0,0),(-1,0),(-1,1),(0,-2),(-1,-2)]),
    ((PieceType::T, RotState::N2, RotState::R), &[(0,0),(-1,0),(-1,1),(0,-2),(-1,-2)]),
    // 2 -> L
    ((PieceType::J, RotState::N2, RotState::L), &[(0,0),(1,0),(1,1),(0,-2),(1,-2)]),
    ((PieceType::T, RotState::N2, RotState::L), &[(0,0),(1,0),(1,1),(0,-2),(1,-2)]),
    // L -> 2
    ((PieceType::J, RotState::L, RotState::N2), &[(0,0),(-1,0),(-1,-1),(0,2),(-1,2)]),
    ((PieceType::T, RotState::L, RotState::N2), &[(0,0),(-1,0),(-1,-1),(0,2),(-1,2)]),
    // L -> 0
    ((PieceType::J, RotState::L, RotState::N0), &[(0,0),(-1,0),(-1,-1),(0,2),(-1,2)]),
    ((PieceType::T, RotState::L, RotState::N0), &[(0,0),(-1,0),(-1,-1),(0,2),(-1,2)]),
    // 0 -> L
    ((PieceType::J, RotState::N0, RotState::L), &[(0,0),(1,0),(1,1),(0,-2),(1,-2)]),
    ((PieceType::T, RotState::N0, RotState::L), &[(0,0),(1,0),(1,1),(0,-2),(1,-2)]),

    // ===== I 型专用 =====
    ((PieceType::I, RotState::N0, RotState::R), &[(0,0),(-2,0),(1,0),(-2,-1),(1,2)]),
    ((PieceType::I, RotState::R, RotState::N0), &[(0,0),(2,0),(-1,0),(2,1),(-1,-2)]),
    ((PieceType::I, RotState::R, RotState::N2), &[(0,0),(-1,0),(2,0),(-1,2),(2,-1)]),
    ((PieceType::I, RotState::N2, RotState::R), &[(0,0),(1,0),(-2,0),(1,-2),(-2,1)]),
    ((PieceType::I, RotState::N2, RotState::L), &[(0,0),(2,0),(-1,0),(2,1),(-1,-2)]),
    ((PieceType::I, RotState::L, RotState::N2), &[(0,0),(-2,0),(1,0),(-2,-1),(1,2)]),
    ((PieceType::I, RotState::L, RotState::N0), &[(0,0),(1,0),(-2,0),(1,-2),(-2,1)]),
    ((PieceType::I, RotState::N0, RotState::L), &[(0,0),(-1,0),(2,0),(-1,2),(2,-1)]),
];

/// 查询 SRS 踢墙偏移量表。
pub fn srs_kick(piece: PieceType, from: RotState, to: RotState) -> &'static [KickOffset] {
    // O 型方块不需要踢墙
    if matches!(piece, PieceType::O) {
        return &[];
    }
    for &((p, f, t), offsets) in SRS_KICKS {
        if p as u8 == piece as u8 && f == from && t == to {
            return offsets;
        }
    }
    // JLSTZ 共享：找不到精确匹配时，尝试按类型组 J/L/S/T/Z 退化返回标准 5 偏移
    const JLSTZ_FALLBACK: &[KickOffset] = &[(0,0),(-1,0),(-1,1),(0,-2),(-1,-2)];
    const I_FALLBACK: &[KickOffset] = &[(0,0),(-2,0),(1,0),(-2,-1),(1,2)];
    match piece {
        PieceType::I => I_FALLBACK,
        _ => JLSTZ_FALLBACK,
    }
}

/// 棋盘：10 列 x 40 行，行 0 为最底行。
pub const BOARD_W: i32 = 10;
pub const BOARD_H: i32 = 40;

#[derive(Debug, Clone)]
pub struct Board {
    cells: Vec<Vec<Option<PieceType>>>,
}

impl Board {
    pub fn new() -> Self {
        Self { cells: vec![vec![None; BOARD_W as usize]; BOARD_H as usize] }
    }
    pub fn get(&self, x: i32, y: i32) -> Option<PieceType> {
        if x < 0 || x >= BOARD_W || y < 0 || y >= BOARD_H { return None; }
        self.cells[y as usize][x as usize]
    }
    pub fn set(&mut self, x: i32, y: i32, p: PieceType) {
        if x < 0 || x >= BOARD_W || y < 0 || y >= BOARD_H { return; }
        self.cells[y as usize][x as usize] = Some(p);
    }
    pub fn is_row_full(&self, y: i32) -> bool {
        if y < 0 || y >= BOARD_H { return false; }
        self.cells[y as usize].iter().all(|c| c.is_some())
    }
    pub fn clear_lines(&mut self) -> u32 {
        let mut cleared = 0u32;
        let mut new_rows: Vec<Vec<Option<PieceType>>> = Vec::new();
        for y in 0..BOARD_H {
            if !self.is_row_full(y) {
                new_rows.push(self.cells[y as usize].clone());
            } else {
                cleared += 1;
            }
        }
        while new_rows.len() < BOARD_H as usize {
            new_rows.insert(0, vec![None; BOARD_W as usize]);
        }
        self.cells = new_rows;
        cleared
    }
}

/// 获取方块在指定旋转状态下的 4 个块相对坐标（相对锚点）。
pub fn piece_cells(piece: PieceType, rot: RotState) -> [(i32, i32); 4] {
    let r = rot as u8;
    match piece {
        PieceType::O => [(0,0),(1,0),(0,1),(1,1)],
        PieceType::I => match r {
            0 => [(0,1),(1,1),(2,1),(3,1)],
            1 => [(2,0),(2,1),(2,2),(2,3)],
            2 => [(0,2),(1,2),(2,2),(3,2)],
            _ => [(1,0),(1,1),(1,2),(1,3)],
        },
        PieceType::T => match r {
            0 => [(0,1),(1,1),(2,1),(1,2)],
            1 => [(1,0),(0,1),(1,1),(1,2)],
            2 => [(0,1),(1,1),(2,1),(1,0)],
            _ => [(1,0),(1,1),(2,1),(1,2)],
        },
        PieceType::S => match r {
            0 => [(1,1),(2,1),(0,2),(1,2)],
            1 => [(1,0),(1,1),(2,1),(2,2)],
            2 => [(1,1),(2,1),(0,2),(1,2)],
            _ => [(0,0),(0,1),(1,1),(1,2)],
        },
        PieceType::Z => match r {
            0 => [(0,1),(1,1),(1,2),(2,2)],
            1 => [(2,0),(1,1),(2,1),(1,2)],
            2 => [(0,1),(1,1),(1,2),(2,2)],
            _ => [(1,0),(0,1),(1,1),(0,2)],
        },
        PieceType::J => match r {
            0 => [(0,0),(0,1),(1,1),(2,1)],
            1 => [(1,0),(2,0),(1,1),(1,2)],
            2 => [(0,1),(1,1),(2,1),(2,2)],
            _ => [(1,0),(1,1),(0,2),(1,2)],
        },
        PieceType::L => match r {
            0 => [(2,0),(0,1),(1,1),(2,1)],
            1 => [(1,0),(1,1),(1,2),(2,2)],
            2 => [(0,1),(1,1),(2,1),(0,2)],
            _ => [(0,0),(1,0),(1,1),(1,2)],
        },
    }
}

/// 判断方块在 (x,y) 位置 + 指定旋转是否合法（越界或与已锁方块重叠均非法）。
pub fn is_valid_position(board: &Board, piece: PieceType, rot: RotState, x: i32, y: i32) -> bool {
    for &(dx, dy) in &piece_cells(piece, rot) {
        let px = x + dx;
        let py = y + dy;
        if px < 0 || px >= BOARD_W || py < 0 || py >= BOARD_H {
            return false;
        }
        if board.get(px, py).is_some() {
            return false;
        }
    }
    true
}

/// 7-Bag 随机发生器：每袋 7 种方块各一次，Fisher-Yates 洗牌。
pub struct BagRandomizer {
    rng_state: u64,
    current_bag: Vec<PieceType>,
}

impl BagRandomizer {
    pub fn new(seed: u64) -> Self {
        let mut s = Self { rng_state: seed.wrapping_add(1), current_bag: Vec::new() };
        s.refill();
        s
    }
    fn next_u64(&mut self) -> u64 {
        // xorshift64
        let mut x = self.rng_state;
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        self.rng_state = x;
        x
    }
    fn refill(&mut self) {
        let mut bag = vec![
            PieceType::I, PieceType::O, PieceType::T, PieceType::S,
            PieceType::Z, PieceType::J, PieceType::L,
        ];
        // Fisher-Yates shuffle
        for i in (1..bag.len()).rev() {
            let j = (self.next_u64() as usize) % (i + 1);
            bag.swap(i, j);
        }
        self.current_bag = bag;
    }
    pub fn next(&mut self) -> PieceType {
        if self.current_bag.is_empty() {
            self.refill();
        }
        self.current_bag.pop().unwrap()
    }
}

/// Ghost 位置计算：返回当前方块合法下落的最大 y（最低点）。
pub fn ghost_y(board: &Board, piece: PieceType, rot: RotState, x: i32, y: i32) -> i32 {
    let mut gy = y;
    while is_valid_position(board, piece, rot, x, gy + 1) {
        gy += 1;
    }
    gy
}

/// 计分函数（单消/双消/三消/四消 × 等级）。
pub fn score_lines(cleared: u32, level: u32) -> u32 {
    let base = match cleared {
        0 => 0,
        1 => 100,
        2 => 300,
        3 => 500,
        _ => 800,
    };
    base * level
}

/// 锁定延迟最大重置次数。
pub const MAX_LOCK_DELAY_RESETS: u32 = 15;
pub const LOCK_DELAY_MS_DEFAULT: u32 = 500;

// 在 lib.rs 内部 include 单元测试模块
#[path = "tests.rs"]
mod tests;
