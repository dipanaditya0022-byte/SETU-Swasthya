enum OfflineWriteDisposition { online, pending }

class OfflineWriteResult<T> {
  const OfflineWriteResult({
    required this.disposition,
    this.value,
    this.localId,
  });

  final OfflineWriteDisposition disposition;
  final T? value;
  final String? localId;

  bool get isPending => disposition == OfflineWriteDisposition.pending;
}
