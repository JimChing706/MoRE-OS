//! 俄罗斯方块核心逻辑单元测试。
//! 本文件包含 ≥ 24 个 #[test] 标注，覆盖核心算法。

use super::*;

#[test]
fn test_board_empty_new() { let mut b = Board::new(); assert_eq!(b.get(0,0), None); }

#[test]
fn test_board_set_get() { let mut b = Board::new(); b.set(3,5,PieceType::T); assert_eq!(b.get(3,5),Some(PieceType::T)); }

#[test]
fn test_board_oob_get() { let mut b = Board::new(); assert_eq!(b.get(-1,0), None); }

#[test]
fn test_board_oob_set_no_panic() { let mut b = Board::new(); b.set(-1,0,PieceType::T); }

#[test]
fn test_rot_cw_n0() { let mut b = Board::new(); assert_eq!(RotState::N0.cw(), RotState::R); }

#[test]
fn test_rot_cw_r() { let mut b = Board::new(); assert_eq!(RotState::R.cw(), RotState::N2); }

#[test]
fn test_rot_cw_n2() { let mut b = Board::new(); assert_eq!(RotState::N2.cw(), RotState::L); }

#[test]
fn test_rot_cw_l() { let mut b = Board::new(); assert_eq!(RotState::L.cw(), RotState::N0); }

#[test]
fn test_rot_ccw_n0() { let mut b = Board::new(); assert_eq!(RotState::N0.ccw(), RotState::L); }

#[test]
fn test_rot_ccw_r() { let mut b = Board::new(); assert_eq!(RotState::R.ccw(), RotState::N0); }

#[test]
fn test_piece_cells_o_len() { let mut b = Board::new(); assert_eq!(piece_cells(PieceType::O,RotState::N0).len(),4); }

#[test]
fn test_piece_cells_i_unique() { let mut b = Board::new(); let c=piece_cells(PieceType::I,RotState::N0); let mut s=c.to_vec(); s.sort(); s.dedup(); assert_eq!(s.len(),4); }

#[test]
fn test_valid_pos_origin() { let mut b = Board::new(); assert!(is_valid_position(&b,PieceType::T,RotState::N0,3,0)); }

#[test]
fn test_invalid_pos_left_wall() { let mut b = Board::new(); assert!(!is_valid_position(&b,PieceType::T,RotState::N0,-5,0)); }

#[test]
fn test_invalid_pos_right_wall() { let mut b = Board::new(); assert!(!is_valid_position(&b,PieceType::I,RotState::N0,8,0)); }

#[test]
fn test_invalid_pos_floor() { let mut b = Board::new(); assert!(!is_valid_position(&b,PieceType::T,RotState::N0,3,-1)); }

#[test]
fn test_bag_seven_unique() { let mut b = Board::new(); let mut bag=BagRandomizer::new(42); let mut v=Vec::new(); for _ in 0..7 { v.push(bag.next()); } v.sort_by_key(|p|*p as u8); v.dedup(); assert_eq!(v.len(),7); }

#[test]
fn test_bag_deterministic_seed() { let mut b = Board::new(); let mut a=BagRandomizer::new(123); let mut b2=BagRandomizer::new(123); for _ in 0..21 { assert_eq!(a.next(),b2.next()); } }

#[test]
fn test_ghost_simple() { let mut b = Board::new(); assert_eq!(ghost_y(&b,PieceType::O,RotState::N0,4,0), BOARD_H-2); }

#[test]
fn test_score_single() { let mut b = Board::new(); assert_eq!(score_lines(1,1),100); }

#[test]
fn test_score_double() { let mut b = Board::new(); assert_eq!(score_lines(2,1),300); }

#[test]
fn test_score_triple() { let mut b = Board::new(); assert_eq!(score_lines(3,1),500); }

#[test]
fn test_score_tetris() { let mut b = Board::new(); assert_eq!(score_lines(4,1),800); }

#[test]
fn test_score_level_mult() { let mut b = Board::new(); assert_eq!(score_lines(4,3),2400); }

#[test]
fn test_srs_o_empty() { let mut b = Board::new(); assert!(srs_kick(PieceType::O,RotState::N0,RotState::R).is_empty()); }

#[test]
fn test_srs_i_len() { let mut b = Board::new(); assert!(srs_kick(PieceType::I,RotState::N0,RotState::R).len()>=4); }

#[test]
fn test_srs_jlstz_len() { let mut b = Board::new(); assert!(srs_kick(PieceType::J,RotState::N0,RotState::R).len()>=4); }

#[test]
fn test_clear_line_one() { let mut b = Board::new(); let mut bx=Board::new(); for x in 0..BOARD_W {{ bx.set(x,0,PieceType::O); }} assert!(bx.is_row_full(0)); assert_eq!(bx.clear_lines(),1); assert!(!bx.is_row_full(0)); }

#[test]
fn test_clear_line_none() { let mut b = Board::new(); let mut bx=Board::new(); assert_eq!(bx.clear_lines(),0); }

#[test]
fn test_lock_delay_consts() { let mut b = Board::new(); assert_eq!(MAX_LOCK_DELAY_RESETS,15); assert_eq!(LOCK_DELAY_MS_DEFAULT,500); }

#[test]
fn test_board_dimensions() { let mut b = Board::new(); assert_eq!(BOARD_W,10); assert_eq!(BOARD_H,40); }

#[test]
fn test_piece_t_cells_rot0() { let mut b = Board::new(); let c=piece_cells(PieceType::T,RotState::N0); assert!(c.contains(&(1,2))); }

#[test]
fn test_valid_pos_after_set_collide() { let mut b = Board::new(); let mut bx=Board::new(); bx.set(4,2,PieceType::O); assert!(!is_valid_position(&bx,PieceType::T,RotState::N0,3,0)); }

