// 요청 흐름 — 같은 출력 영역을 갱신하는 요청 가운데 '최신 요청'만 화면에 반영한다. DOM에 의존하지 않는다 (node로 시험).
//
// 서랍 세대(alive)는 '다른 서랍으로 갔는가'를, 요청 관문(gate)은 '같은 서랍 안에서 더 새 요청이 있는가'를 본다.
// 둘 다 통과한 요청만 성공 · 오류 · 로딩 해제를 반영한다. (디자인 v2 리뷰 P2 — 같은 서랍 연속 요청)
//
//   예: 조건 칩 first → second 를 연달아 누르고 응답이 second → first 순서로 오면
//       second 결과만 남고, 늦게 온 first 의 결과 · 오류 · 로딩 해제는 버린다.

export function requestGate() {
  let seq = 0;
  return {
    // 새 요청 시작 — 이전 요청은 모두 '지난 요청'이 된다
    start() {
      const mine = ++seq;
      return () => mine === seq;
    },
    // 진행 중인 요청을 모두 무효로 (예: 대화 삭제가 이전 기록 조회 응답을 막을 때)
    invalidate() {
      seq += 1;
    },
  };
}

// 관문 · 서랍 세대를 지키는 실행 — 최신 요청일 때만 onStart 다음 단계를 반영한다
export async function runLatest(gate, alive, { work, onStart, onSuccess, onError, onSettled }) {
  const isLatest = gate.start();
  const current = () => alive() && isLatest();
  onStart?.();
  try {
    const result = await work();
    if (current()) onSuccess?.(result);
  } catch (e) {
    if (current()) onError?.(e);
  } finally {
    if (current()) onSettled?.();      // 지난 요청이 새 요청의 로딩 상태를 풀지 않게
  }
}

// 대화 기록 삭제 — 서버 삭제가 성공한 뒤에만 화면 기록을 지운다
//   실패: 기록을 그대로 두고 오류를 알린다 (다시 시도할 수 있다)
//   진행 중: 중복 삭제를 막고, 먼저 시작된 기록 조회 응답이 지운 기록을 되살리지 않게 history 관문을 무효로
export function clearHistoryFlow({ request, historyGate, alive, onBusy, onCleared, onFailed }) {
  let pending = false;
  return async () => {
    if (pending) return false;
    pending = true;
    historyGate?.invalidate();
    onBusy?.(true);
    try {
      await request();
      if (alive()) onCleared?.();
      return true;
    } catch (e) {
      if (alive()) onFailed?.(e);
      return false;
    } finally {
      pending = false;
      if (alive()) onBusy?.(false);
    }
  };
}
