package io.junction.trails.media.web;

import io.junction.trails.media.model.MediaException;
import java.util.Locale;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.http.ProblemDetail;
import org.springframework.transaction.CannotCreateTransactionException;
import org.springframework.transaction.TransactionSystemException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;

@RestControllerAdvice(assignableTypes = MediaController.class)
@Order(Ordered.HIGHEST_PRECEDENCE)
class MediaExceptionHandler {
    @ExceptionHandler(MediaException.class)
    ProblemDetail mediaFailure(MediaException exception) {
        var problem = ProblemDetail.forStatusAndDetail(
                org.springframework.http.HttpStatusCode.valueOf(exception.getReason().getStatus()), exception.getMessage());
        problem.setProperty("code", exception.getReason().name().toLowerCase(Locale.ROOT));
        return problem;
    }

    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    ProblemDetail invalidRequest(Exception exception) {
        return mediaFailure(new MediaException(MediaException.Reason.INVALID_REQUEST));
    }

    @ExceptionHandler({DataAccessResourceFailureException.class, CannotCreateTransactionException.class,
            TransactionSystemException.class})
    ProblemDetail storageUnavailable(Exception exception) {
        return mediaFailure(new MediaException(MediaException.Reason.STORAGE_UNAVAILABLE));
    }
}
