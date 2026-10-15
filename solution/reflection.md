# Thu hoạch: Phát hiện lỗi trong Data Siege

Trong năm luồng sự kiện, khó nhất là các lỗi lệch phân phối ở
`feature_materialization` và `embedding_batch`. Giá trị của chúng có thể gần
dao động tự nhiên của dữ liệu sạch nên một ngưỡng quá chặt sẽ bỏ sót lỗi, còn
ngưỡng quá nhạy sẽ tạo nhiều cảnh báo giả. Ở `data_batch`, từng chỉ số như số
hàng hoặc độ trễ có thể vẫn nằm trong giới hạn nhưng nhiều chỉ số cùng lệch
theo một hướng. Vì vậy, ngoài kiểm tra từng ngưỡng, tôi dùng khoảng cách
đa chiều để nhận diện thay đổi đồng thời. Các lỗi contract như sai schema,
sai kiểu dữ liệu và lỗi lineage như thiếu upstream dễ phân loại hơn vì tool
trả về bằng chứng trực tiếp.

Chiến lược chi phí của tôi là chỉ gọi một tool phù hợp cho mỗi sự kiện, không
gọi lặp để kiểm tra cùng một dữ liệu. Cách này tốn 180 credits ở Practice và
240 credits ở Public. Public vượt ngân sách 20 credits, tương ứng overage
0.0909 và penalty 1.82 điểm. Tôi chấp nhận khoản phạt này thay vì cắt bớt lượt
đo, vì bỏ lượt đo có thể làm giảm TPR, mỗi sự kiện chỉ gọi một tool phù hợp
để kiểm soát chi phí mà vẫn theo dõi đủ các luồng. Sau khi đối chiếu Practice,
tôi nâng ngưỡng composite từ 1.30 lên 3.40 vì ngưỡng cũ báo nhầm trên các batch
sạch. Kết quả cuối đạt TPR 100%, FPR 0% ở Practice và Public, cả bốn trụ cột
đều đạt band `high` ở Public. Tôi giữ các ngưỡng đó cho Private để tránh tiếp
tục khớp theo một bộ dữ liệu đã biết.

Nếu có thêm thời gian, tôi sẽ dùng `ctx.state` lưu thống kê theo từng bảng,
feature view và corpus thay vì gộp mọi nguồn vào một phân phối chung. Một cửa
sổ trượt có thể theo dõi trung vị và MAD (độ lệch tuyệt đối trung vị) hoặc dùng
EWMA để nhận ra dịch chuyển kéo dài mà không phản ứng quá mạnh với một batch
đơn lẻ. Các giá trị chỉ nên cập nhật khi sự kiện nằm trong vùng sạch theo
baseline và không có vi phạm contract hay lineage, như vậy lỗi mới xuất hiện
ít có cơ hội kéo chuẩn tham chiếu về phía mình. Tôi cũng sẽ đánh giá riêng
ngưỡng theo từng nhóm dữ liệu và theo dõi tỷ lệ cảnh báo giả trước khi đưa
thay đổi vào luồng Private.
