# -*- coding: utf-8 -*-
import tictactoe_env

import time
from collections import deque, defaultdict

import numpy as np
import slackweb


PLAYER = 0
OPPONENT = 1
MARK_O = 2
N, W, Q, P = 0, 1, 2, 3
EPISODE = 800
SAVE_CYCLE = 800


class MCTS(object):
    """몬테카를로 트리 탐색 클래스

    시뮬레이션을 통해 train 데이터 생성 (state, edge 저장)

    state
    ------
    각 주체당 4수까지 저장해서 state_new로 만듦

        9x3x3 numpy array -> 1x81 tuple (저장용)

    edge
    -----
    현재 state에서 착수 가능한 모든 action자리에 4개의 정보 저장

    type: 3x3x4 numpy array

        9개 좌표에 4개의 정보 N, W, Q, P 매칭
        N: edge 방문횟수, W: 보상누적값, Q: 보상평균(W/N), P: edge 선택 사전확률
        edge[좌표행][좌표열][번호]로 접근

    """

    def __init__(self):
        # memories
        self.state_memory = deque(maxlen=9 * EPISODE)
        self.node_memory = deque(maxlen=9 * EPISODE)
        self.edge_memory = deque(maxlen=9 * EPISODE)

        # hyperparameter
        self.c_puct = 5
        self.epsilon = 0.25
        self.alpha = 0.7

        # reset_step member
        self.tree_memory = None
        self.pr = None
        self.puct = None
        self.edge = None
        self.legal_move_n = None
        self.empty_loc = None
        self.total_visit = None
        self.first_turn = None
        self.user_type = None
        self.state_new = None
        self.state_hash = None

        # reset_episode member
        self.action_memory = None
        self.action_count = None
        self.my_history = None
        self.your_history = None
        self.board = None
        self.state = None

        # member 초기화
        self._reset_step()
        self._reset_episode()

    def _reset_step(self):
        self.tree_memory = defaultdict(lambda: 0)
        self.edge = np.zeros((3, 3, 4), 'float')
        self.puct = np.zeros((3, 3), 'float')
        self.total_visit = 0
        self.legal_move_n = 0
        self.pr = 0
        self.empty_loc = None
        self.state_hash = None
        self.state_new = None
        self.user_type = None

    def _reset_episode(self):
        plane = np.zeros((3, 3)).flatten()
        self.my_history = deque([plane, plane, plane, plane], maxlen=4)
        self.your_history = deque([plane, plane, plane, plane], maxlen=4)
        self.action_memory = deque(maxlen=9)
        self.action_count = 0
        self.board = None
        self.first_turn = None
        self.user_type = None

    def select_action(self, state):
        """raw state를 받아 변환 및 저장 후 action을 리턴하는 외부 메소드.

        state 변환
        ----------
        state -> state_new -> state_hash

            state_new: 9x3x3 numpy array.
                유저별 최근 4-histroy 저장하여 재구성. (저장용)

            state_hash: str. (hash)
                state_new를 string으로 바꾼 후 hash 생성. (탐색용)
                node로 부름.

        action 선택
        -----------
        puct 값이 가장 높은 곳을 선택함, 동점이면 랜덤 선택.

            action: 1x3 tuple.
                action = (주체 인덱스, 보드의 x좌표, 보드의 y좌표)

        """
        # ------------------------ 턴 계산 ------------------------ #
        self.action_count += 1
        # 호출될 때마다 첫턴 기준 교대로 행동주체 바꿈, 최종 action에 붙여줌
        self.user_type = (self.first_turn + self.action_count - 1) % 2

        # ------------------- state 변환 및 저장 ------------------- #
        self.state = state.copy()
        self.state_new = self._convert_state(state)
        # 새로운 state 저장
        self.state_memory.appendleft(self.state_new)
        # state를 문자열 -> hash로 변환 (dict의 key로 쓰려고)
        self.state_hash = hash(self.state_new.tostring())
        # 변환한 state를 node로 부르자. 저장!
        self.node_memory.appendleft(self.state_hash)

        # ------------ 들어온 state에 대응하는 edge 초기화 ------------ #
        self.init_edge()

        # ------------- 저장 데이터를 사용하여 PUCT 값 계산 ------------ #
        self._cal_puct()

        # 점수 확인
        print("* PUCT Score *")
        print(self.puct.round(decimals=2))

        # 값이 음수가 나올 수 있어서 빈자리가 아닌 곳은 -9999를 넣어 최댓값 방지
        puct = self.puct.tolist()
        for i, v in enumerate(puct):
            for k, s in enumerate(v):
                if [i, k] not in self.empty_loc.tolist():
                    puct[i][k] = -9999

        # ----------------- PUCT가 최댓값인 곳 찾기 ----------------- #
        self.puct = np.asarray(puct)
        puct_max = np.argwhere(self.puct == self.puct.max()).tolist()
        # 동점 처리
        move_target = puct_max[np.random.choice(len(puct_max))]

        # -------------------- 최종 action 구성 -------------------- #
        # 배열 접붙히기
        action = np.r_[self.user_type, move_target]

        # ---------------- action 저장 및 step 초기화 ---------------- #
        self.action_memory.appendleft(action)
        self._reset_step()
        return tuple(action)

    def _convert_state(self, state):
        """ state변환 메소드: action 주체별 최대 4수까지 history를 저장하여 새로운 state로 구성"""
        if abs(self.user_type - 1) == PLAYER:
            self.my_history.appendleft(state[PLAYER].flatten())
        else:
            self.your_history.appendleft(state[OPPONENT].flatten())
        state_new = np.r_[np.array(self.my_history).flatten(),
                          np.array(self.your_history).flatten(),
                          self.state[2].flatten()]
        return state_new

    def init_edge(self, pr=None):
        """들어온 state에서 착수 가능한 edge 초기화 메소드 (P값 배치)

        빈자리를 검색하여 규칙위반 방지 및 랜덤 확률 생성
        root node 확인 후 노이즈 줌 (e-greedy)
        """
        # 들어 온 사전확률이 없으면
        if pr is None:
            # 빈 자리의 좌표와 개수를 저장하고 이를 이용해 동일 확률을 계산
            self.board = self.state[PLAYER] + self.state[OPPONENT]
            self.empty_loc = np.argwhere(self.board == 0)
            self.legal_move_n = self.empty_loc.shape[0]
            prob = 1 / self.legal_move_n
            count = self.node_memory.count(self.state_hash)
            # state 방문횟수 출력
            print('visit count: {}'.format(count))
            # root node면
            if self.action_count == 1:
                self.pr = (1 - self.epsilon) * prob + self.epsilon * \
                    np.random.dirichlet(
                        self.alpha * np.ones(self.legal_move_n))
            else:  # 아니면 랜덤 확률로 n분의 1
                self.pr = prob * np.ones(self.legal_move_n)

            # 빈자리의 엣지에 넣기
            for i in range(self.legal_move_n):
                self.edge[self.empty_loc[i][0]
                          ][self.empty_loc[i][1]][P] = self.pr[i]
        else:  # 사전확률 값이 들어오면 그걸로 넣기 (신경망이 사용할 예정)
            self.pr = pr
            for i in range(3):
                for k in range(3):
                    self.edge[i][k][P] = self.pr[i][k]
        # edge 메모리에 저장
        self.edge_memory.appendleft(self.edge)

    def _cal_puct(self):
        """9개의 좌표에 PUCT값을 계산하여 매칭하는 메소드"""
        # 지금까지의 액션을 반영한 트리 구성 하기. dict{node: edge}
        memory = list(zip(self.node_memory, self.edge_memory))
        # 지금까지의 동일한 state에 대한 edge의 N,W 누적
        # Q, P는 덧셈이라 손상되므로 보정함
        for v in memory:
            key = v[0]
            value = v[1]
            self.tree_memory[key] += value
        if self.node_memory[0] in self.tree_memory:
            edge = self.tree_memory[self.node_memory[0]]
            for i in range(3):
                for k in range(3):
                    self.total_visit += edge[i][k][N]
            for c in range(3):
                for r in range(3):
                    if edge[c][r][N] != 0:
                        # Q 보정
                        edge[c][r][Q] = edge[c][r][W] / edge[c][r][N]
                    # P 보정
                    edge[c][r][P] = self.edge[c][r][P]
                    # PUCT 계산!
                    self.puct[c][r] = edge[c][r][Q] + \
                        self.c_puct * \
                        edge[c][r][P] * \
                        np.sqrt(self.total_visit) / (1 + edge[c][r][N])
            # 보정한 edge를 최종 트리에 업데이트
            self.tree_memory[self.node_memory[0]] = edge

    def backup(self, reward):
        """에피소드가 끝나면 지나온 edge의 N과 W를 업데이트"""
        steps = self.action_count
        for i in range(steps):
            if self.action_memory[i][0] == PLAYER:
                self.edge_memory[i][self.action_memory[i][1]
                                    ][self.action_memory[i][2]
                                      ][W] += reward
            else:
                self.edge_memory[i][self.action_memory[i][1]
                                    ][self.action_memory[i][2]
                                      ][W] -= reward
            self.edge_memory[i][self.action_memory[i][1]
                                ][self.action_memory[i][2]][N] += 1
        self._reset_episode()


if __name__ == "__main__":
    start = time.time()
    # 환경 생성
    env = tictactoe_env.TicTacToeEnv()
    # 셀프 플레이 인스턴스 생성
    zero_play = MCTS()
    # 통계용
    result = {1: 0, 0: 0, -1: 0}
    win_mark_O = 0
    # 초기 train data 생성 루프
    for e in range(EPISODE):
        # state 생성
        state = env.reset()
        print('-' * 22, '\nepisode: %d' % (e + 1))
        # 선공 정하고 교대로 하기
        zero_play.first_turn = (PLAYER + e) % 2
        env.player_color = zero_play.first_turn
        done = False
        step = 0
        while not done:
            step += 1
            print('step: %d' % step)

            # 보드 상황 출력: 내 착수:1, 상대 착수:2
            print("---- BOARD ----")
            print(state[PLAYER] + state[OPPONENT] * 2)

            # action 선택하기
            action = zero_play.select_action(state)
            # step 진행
            state, reward, done, info = env.step(action)
        if done:

            # 승부난 보드 보기
            print("- FINAL BOARD -")
            print(state[PLAYER] + state[OPPONENT] * 2)

            # 보상을 edge에 백업
            zero_play.backup(reward)
            # 결과 체크
            result[reward] += 1
            # 선공으로 이긴 경우 체크
            if reward == 1:
                if env.player_color == 0:
                    win_mark_O += 1
        # 데이터 저장
        if (e + 1) % SAVE_CYCLE == 0:
            # 메시지 보내기
            finish = round(float(time.time() - start))
            print('%d episode data saved' % (e + 1))
            np.save('data/state_memory_e{}_c{}a{}.npy'.format(
                (e + 1),
                zero_play.c_puct,
                zero_play.alpha),
                zero_play.state_memory)
            np.save('data/edge_memory_e{}_c{}a{}.npy'.format(
                (e + 1),
                zero_play.c_puct,
                zero_play.alpha),
                zero_play.edge_memory)

            # 에피소드 통계
            statics = ('\nWin: %d  Lose: %d  Draw: %d  Winrate: %0.1f%%  \
WinMarkO: %d' % (result[1], result[-1], result[0],
                 1 / (1 + np.exp(result[-1] / EPISODE) /
                      np.exp(result[1] / EPISODE)) * 100,
                 win_mark_O))
            print('-' * 22, statics)

            slack = slackweb.Slack(
                url="https://hooks.slack.com/services/T8P0E384U/B8PR44F1C/\
4gVy7zhZ9teBUoAFSse8iynn")
            slack.notify(
                text="Finished: {} episode in {}s".format(e + 1, finish))
            slack.notify(text=statics)
